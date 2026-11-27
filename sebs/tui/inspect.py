# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Interactive Textual TUI for read-only inspection of the SeBS cache.

The inspector renders the on-disk cache as an interactive tree grouped by cloud
system and, within each cloud, by resource class (benchmarks, functions,
triggers and URLs, storage buckets, NoSQL tables, resource groups, and locally
allocated ports). Selecting a node in the tree updates a detail table on the
right, so complex experiments with many allocated resources stay readable
instead of collapsing into one busy printout.

The heavy widget logic lives in :class:`ResourceInspectorApp`, but the grouping
itself is performed by the pure :func:`build_inventory` helper so it can be unit
tested without launching a terminal application.
"""

from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode


# The stable order in which resource classes are shown under each cloud.
RESOURCE_CLASSES: List[str] = [
    "Benchmarks",
    "Functions",
    "Triggers & URLs",
    "Storage buckets",
    "NoSQL tables",
    "Resource groups",
    "Allocated ports",
]


def _clouds_in_use(
    benchmarks: List[Dict[str, Any]], allocated: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Return the sorted set of clouds referenced by benchmarks or resources.

    Args:
        benchmarks: Rows from :meth:`sebs.cache.Cache.get_deployed_benchmarks`.
        allocated: Mapping from :meth:`sebs.cache.Cache.get_allocated_resources`.

    Returns:
        Sorted list of platform names that appear in either input.
    """
    clouds = {row["platform"] for row in benchmarks}
    clouds.update(allocated.keys())
    return sorted(clouds)


def build_inventory(
    benchmarks: List[Dict[str, Any]], allocated: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Group flat cache rows into a per-cloud, per-resource-class inventory.

    This is the pure data transform that backs the TUI. It reshapes the two flat
    cache views into a nested structure keyed first by cloud and then by resource
    class, attaching a small summary (resources id and region) per cloud.

    Args:
        benchmarks: Rows from :meth:`sebs.cache.Cache.get_deployed_benchmarks`.
        allocated: Mapping from :meth:`sebs.cache.Cache.get_allocated_resources`.

    Returns:
        Mapping of cloud name to a dict with two keys: ``summary`` (a dict with
        ``resources_id`` and ``region``) and ``classes`` (a mapping of resource
        class name to a list of row dicts describing each entry).
    """
    inventory: Dict[str, Dict[str, Any]] = {}

    for cloud in _clouds_in_use(benchmarks, allocated):
        cloud_benchmarks = [row for row in benchmarks if row["platform"] == cloud]
        resources = allocated.get(cloud, {})

        classes: Dict[str, List[Dict[str, Any]]] = {name: [] for name in RESOURCE_CLASSES}

        for row in cloud_benchmarks:
            classes["Benchmarks"].append(
                {
                    "benchmark": row["benchmark"],
                    "language": row["language"],
                    "packaging": row["packaging"],
                    "functions": len(row.get("functions", [])),
                    "triggers": ", ".join(row.get("triggers", [])) or "-",
                }
            )
            for func in row.get("function_details", []):
                classes["Functions"].append(
                    {
                        "name": func["name"],
                        "benchmark": row["benchmark"],
                        "language": row["language"],
                        "hash": func.get("hash") or "-",
                        "triggers": ", ".join(func.get("triggers", [])) or "-",
                    }
                )
                for trigger in func.get("trigger_details", []):
                    classes["Triggers & URLs"].append(
                        {
                            "benchmark": row["benchmark"],
                            "function": func["name"],
                            "type": trigger.get("type") or "-",
                            "implementation": trigger.get("implementation") or "-",
                            "url": trigger.get("url") or "-",
                        }
                    )

        # Storage buckets: allocated buckets plus any referenced per benchmark.
        seen_buckets = set()
        for name, value in (resources.get("storage_buckets") or {}).items():
            key = str(value) if value else name
            if key in seen_buckets:
                continue
            seen_buckets.add(key)
            classes["Storage buckets"].append({"name": key, "role": name})
        for account in resources.get("storage_accounts") or []:
            if account in seen_buckets:
                continue
            seen_buckets.add(account)
            classes["Storage buckets"].append({"name": account, "role": "storage_account"})
        for row in cloud_benchmarks:
            for bucket in row.get("storage", []):
                if bucket in seen_buckets:
                    continue
                seen_buckets.add(bucket)
                classes["Storage buckets"].append({"name": bucket, "role": "benchmark"})

        # NoSQL tables: per-benchmark tables plus a cloud-level NoSQL account.
        seen_tables = set()
        for row in cloud_benchmarks:
            for table in row.get("nosql", []):
                if table in seen_tables:
                    continue
                seen_tables.add(table)
                classes["NoSQL tables"].append({"name": table, "benchmark": row["benchmark"]})
        nosql_account = resources.get("nosql") or {}
        account_name = nosql_account.get("account_name") or nosql_account.get("name")
        if account_name and account_name not in seen_tables:
            seen_tables.add(account_name)
            classes["NoSQL tables"].append({"name": account_name, "benchmark": "(account)"})

        resource_group = resources.get("resource_group")
        if resource_group:
            classes["Resource groups"].append({"name": resource_group})

        for port in resources.get("allocated_ports") or []:
            classes["Allocated ports"].append({"port": str(port)})

        inventory[cloud] = {
            "summary": {
                "resources_id": resources.get("resources_id"),
                "region": resources.get("region"),
            },
            "classes": classes,
        }

    return inventory


# Column layout for the detail table, keyed by resource class name.
_CLASS_COLUMNS: Dict[str, List[str]] = {
    "Benchmarks": ["benchmark", "language", "packaging", "functions", "triggers"],
    "Functions": ["name", "benchmark", "language", "hash", "triggers"],
    "Triggers & URLs": ["benchmark", "function", "type", "implementation", "url"],
    "Storage buckets": ["name", "role"],
    "NoSQL tables": ["name", "benchmark"],
    "Resource groups": ["name"],
    "Allocated ports": ["port"],
}


class ResourceInspectorApp(App):
    """Textual application that visualises the SeBS cache interactively.

    The left pane is a tree grouping resources by cloud system and resource
    class; the right pane is a detail table that reflects the highlighted node.
    """

    CSS = """
    Tree {
        width: 40%;
        border: round $primary;
    }
    #detail {
        width: 60%;
    }
    #summary {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("e", "expand_all", "Expand all"),
        ("c", "collapse_all", "Collapse all"),
    ]

    def __init__(
        self,
        benchmarks: List[Dict[str, Any]],
        allocated: Dict[str, Dict[str, Any]],
    ) -> None:
        """Store the cache views and precompute the grouped inventory.

        Args:
            benchmarks: Rows from
                :meth:`sebs.cache.Cache.get_deployed_benchmarks`.
            allocated: Mapping from
                :meth:`sebs.cache.Cache.get_allocated_resources`.
        """
        super().__init__()
        self._benchmarks = benchmarks
        self._allocated = allocated
        self._inventory = build_inventory(benchmarks, allocated)

    def compose(self) -> ComposeResult:
        """Build the widget hierarchy for the application.

        Yields:
            The header, the tree/detail split, and the footer widgets.
        """
        yield Header(show_clock=False)
        with Horizontal():
            yield Tree("SeBS cache", id="tree")
            with Horizontal(id="detail"):
                yield DataTable(id="table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="summary")
        yield Footer()

    def on_mount(self) -> None:
        """Populate the tree once the DOM is ready and focus it."""
        self.title = "SeBS Resource Inspector"
        tree = self.query_one("#tree", Tree)
        tree.root.data = {"kind": "root"}
        tree.root.expand()

        if not self._inventory:
            tree.root.add_leaf("No cached resources found", data={"kind": "empty"})
            self.query_one("#summary", Static).update(
                "Cache is empty or contains no deployed benchmarks or allocated resources."
            )
            return

        for cloud, entry in self._inventory.items():
            cloud_node = tree.root.add(cloud, data={"kind": "cloud", "cloud": cloud})
            cloud_node.expand()
            for class_name in RESOURCE_CLASSES:
                rows = entry["classes"].get(class_name, [])
                label = f"{class_name} ({len(rows)})"
                class_node = cloud_node.add(
                    label,
                    data={"kind": "class", "cloud": cloud, "class": class_name, "rows": rows},
                )
                for row in rows:
                    class_node.add_leaf(
                        self._leaf_label(class_name, row),
                        data={
                            "kind": "item",
                            "cloud": cloud,
                            "class": class_name,
                            "rows": [row],
                        },
                    )
        tree.focus()

    @staticmethod
    def _leaf_label(class_name: str, row: Dict[str, Any]) -> str:
        """Return a short label for a single resource entry.

        Args:
            class_name: Resource class the row belongs to.
            row: The row dict describing the entry.

        Returns:
            A concise, human-readable label for the tree leaf.
        """
        if class_name == "Benchmarks":
            return f"{row['benchmark']} [{row['language']}]"
        if class_name == "Functions":
            return row["name"]
        if class_name == "Triggers & URLs":
            return f"{row['type']}: {row['url']}"
        if class_name == "Allocated ports":
            return row["port"]
        return str(row.get("name", next(iter(row.values()), "-")))

    def _render_rows(self, class_name: str, rows: List[Dict[str, Any]]) -> None:
        """Render a set of resource rows into the detail table.

        Args:
            class_name: Resource class whose column layout should be used.
            rows: Row dicts to display.
        """
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        columns = _CLASS_COLUMNS.get(class_name, [])
        if not columns:
            return
        table.add_columns(*[col.replace("_", " ").title() for col in columns])
        for row in rows:
            table.add_row(*[str(row.get(col, "-")) for col in columns])

    def _show_summary(self, cloud: Optional[str]) -> None:
        """Update the summary line for the selected cloud.

        Args:
            cloud: Cloud whose summary to show, or None to clear it.
        """
        summary = self.query_one("#summary", Static)
        if cloud is None or cloud not in self._inventory:
            summary.update("")
            return
        info = self._inventory[cloud]["summary"]
        rid = info.get("resources_id") or "-"
        region = info.get("region") or "-"
        summary.update(f"{cloud}   resources_id: {rid}   region: {region}")

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """React to tree navigation by updating the detail table and summary.

        Args:
            event: The highlight event carrying the focused tree node.
        """
        self._update_from_node(event.node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """React to explicit node selection identically to highlighting.

        Args:
            event: The selection event carrying the chosen tree node.
        """
        self._update_from_node(event.node)

    def _update_from_node(self, node: TreeNode) -> None:
        """Refresh the detail panels from the given tree node's payload.

        Args:
            node: The tree node whose attached data drives the detail view.
        """
        data = node.data or {}
        kind = data.get("kind")
        cloud = data.get("cloud")
        self._show_summary(cloud)

        if kind in ("class", "item"):
            self._render_rows(data["class"], data.get("rows", []))
        else:
            table = self.query_one("#table", DataTable)
            table.clear(columns=True)

    def action_expand_all(self) -> None:
        """Expand every node in the tree."""
        self.query_one("#tree", Tree).root.expand_all()

    def action_collapse_all(self) -> None:
        """Collapse every node back to the cloud level."""
        tree = self.query_one("#tree", Tree)
        for cloud_node in tree.root.children:
            cloud_node.collapse_all()
            cloud_node.expand()


def run_inspector(benchmarks: List[Dict[str, Any]], allocated: Dict[str, Dict[str, Any]]) -> None:
    """Launch the interactive resource inspector.

    Args:
        benchmarks: Rows from
            :meth:`sebs.cache.Cache.get_deployed_benchmarks`.
        allocated: Mapping from
            :meth:`sebs.cache.Cache.get_allocated_resources`.
    """
    ResourceInspectorApp(benchmarks, allocated).run()

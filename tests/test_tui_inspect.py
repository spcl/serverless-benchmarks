#!/usr/bin/env python3
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Unit tests for the interactive cache-inspection TUI.

These tests exercise the pure grouping helper (:func:`build_inventory`) directly
and drive the Textual application headlessly through its test ``Pilot`` so the
widget wiring is covered without a real terminal. They run fully offline.
"""

import unittest

from sebs.tui.inspect import RESOURCE_CLASSES, ResourceInspectorApp, build_inventory


def _sample_inputs():
    """Return representative benchmark and allocated-resource fixtures.

    Returns:
        Tuple of (benchmarks, allocated) matching the shape produced by
        ``Cache.get_deployed_benchmarks`` and ``Cache.get_allocated_resources``.
    """
    benchmarks = [
        {
            "benchmark": "110.dynamic-html",
            "platform": "aws",
            "language": "python",
            "packaging": "code_package",
            "functions": ["fn-1"],
            "function_details": [
                {
                    "name": "fn-1",
                    "hash": "deadbeef",
                    "triggers": ["http", "library"],
                    "trigger_details": [
                        {"type": "library", "url": None, "implementation": None},
                        {
                            "type": "http",
                            "url": "https://example.execute-api.amazonaws.com/x",
                            "implementation": "api_gateway",
                        },
                    ],
                }
            ],
            "triggers": ["http", "library"],
            "urls": ["https://example.execute-api.amazonaws.com/x"],
            "storage": ["sebs-benchmarks-abc"],
            "nosql": ["sebs-table-abc"],
        }
    ]
    allocated = {
        "aws": {
            "resources_id": "abc123",
            "region": "us-east-1",
            "storage_buckets": {"benchmarks": "sebs-benchmarks-abc"},
            "allocated_ports": [],
            "resource_group": None,
            "storage_accounts": [],
            "nosql": {},
        },
        "local": {
            "resources_id": "local42",
            "region": None,
            "storage_buckets": {},
            "allocated_ports": [9000, 9001],
            "resource_group": None,
            "storage_accounts": [],
            "nosql": {},
        },
    }
    return benchmarks, allocated


class BuildInventoryTests(unittest.TestCase):
    """Verify the pure grouping transform behind the TUI."""

    def test_groups_by_cloud_and_class(self) -> None:
        """Every cloud is present and keyed by the known resource classes."""
        benchmarks, allocated = _sample_inputs()
        inventory = build_inventory(benchmarks, allocated)

        self.assertEqual(sorted(inventory.keys()), ["aws", "local"])
        for cloud in inventory.values():
            self.assertEqual(list(cloud["classes"].keys()), RESOURCE_CLASSES)

    def test_aws_classes_populated(self) -> None:
        """AWS groups its benchmark, function, trigger, storage, and NoSQL rows."""
        benchmarks, allocated = _sample_inputs()
        classes = build_inventory(benchmarks, allocated)["aws"]["classes"]

        self.assertEqual(len(classes["Benchmarks"]), 1)
        self.assertEqual(len(classes["Functions"]), 1)
        triggers = classes["Triggers & URLs"]
        self.assertEqual(len(triggers), 2)
        http = [t for t in triggers if t["type"] == "http"][0]
        self.assertEqual(http["url"], "https://example.execute-api.amazonaws.com/x")
        self.assertEqual([b["name"] for b in classes["Storage buckets"]], ["sebs-benchmarks-abc"])
        self.assertEqual([t["name"] for t in classes["NoSQL tables"]], ["sebs-table-abc"])

    def test_local_ports_grouped(self) -> None:
        """Local allocated ports become individual rows under their class."""
        benchmarks, allocated = _sample_inputs()
        classes = build_inventory(benchmarks, allocated)["local"]["classes"]
        self.assertEqual([p["port"] for p in classes["Allocated ports"]], ["9000", "9001"])

    def test_empty_inputs(self) -> None:
        """Empty cache inputs yield an empty inventory."""
        self.assertEqual(build_inventory([], {}), {})


class ResourceInspectorAppTests(unittest.IsolatedAsyncioTestCase):
    """Drive the Textual application headlessly through its test Pilot."""

    async def test_tree_populates_and_selection_fills_table(self) -> None:
        """Mounting builds the cloud tree and selecting a class fills the table."""
        benchmarks, allocated = _sample_inputs()
        app = ResourceInspectorApp(benchmarks, allocated)
        async with app.run_test() as pilot:
            from textual.widgets import DataTable, Tree

            tree = app.query_one("#tree", Tree)
            cloud_labels = sorted(str(node.label) for node in tree.root.children)
            self.assertEqual(cloud_labels, ["aws", "local"])

            # Find the AWS "Benchmarks" class node and select it.
            aws_node = [n for n in tree.root.children if str(n.label) == "aws"][0]
            bench_node = [
                n for n in aws_node.children if str(n.label).startswith("Benchmarks")
            ][0]
            tree.select_node(bench_node)
            await pilot.pause()

            table = app.query_one("#table", DataTable)
            self.assertGreater(table.row_count, 0)

    async def test_empty_cache_shows_message(self) -> None:
        """An empty cache renders a placeholder leaf instead of cloud nodes."""
        app = ResourceInspectorApp([], {})
        async with app.run_test() as pilot:
            await pilot.pause()
            from textual.widgets import Tree

            tree = app.query_one("#tree", Tree)
            labels = [str(node.label) for node in tree.root.children]
            self.assertEqual(len(labels), 1)
            self.assertIn("No cached resources", labels[0])


if __name__ == "__main__":
    unittest.main()

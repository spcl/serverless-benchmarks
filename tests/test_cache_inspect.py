#!/usr/bin/env python3
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Unit tests for the read-only cache inspection API.

These tests build a synthetic cache directory on disk (per-cloud `<cloud>.json`
files plus per-benchmark `config.json` files) and verify that
`Cache.get_deployed_benchmarks` and `Cache.get_allocated_resources` flatten the
model correctly. They run fully offline and require no Docker daemon.
"""

import json
import os
import tempfile
import unittest

from sebs.cache import Cache


def _write_json(path: str, data: dict) -> None:
    """Write a dictionary as JSON to a path, creating parent directories.

    Args:
        path: Destination file path.
        data: JSON-serializable dictionary to write.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fp:
        json.dump(data, fp)


class CacheInspectTests(unittest.TestCase):
    """Verify the read-only inspection helpers on a synthetic cache."""

    def setUp(self) -> None:
        """Create a temporary cache directory with representative content."""
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = self._tmp.name

        # Per-cloud resource files.
        _write_json(
            os.path.join(self.cache_dir, "aws.json"),
            {
                "region": "us-east-1",
                "resources": {
                    "resources_id": "abc123",
                    "storage_buckets": {
                        "benchmarks": "sebs-benchmarks-abc123",
                        "experiments": "sebs-experiments-abc123",
                    },
                },
            },
        )
        _write_json(
            os.path.join(self.cache_dir, "azure.json"),
            {
                "region": "westeurope",
                "resources": {
                    "resources_id": "az777",
                    "resource_group": "sebs_resource_group_az777",
                    "storage_accounts": [{"account_name": "sebsstorageaz777"}],
                    "cosmosdb_account": {"account_name": "sebs-cosmos-az777"},
                },
            },
        )
        _write_json(
            os.path.join(self.cache_dir, "local.json"),
            {
                "resources": {
                    "resources_id": "local42",
                    "allocated_ports": [9000, 9001],
                },
            },
        )

        # Per-benchmark config with a deployed AWS python function.
        _write_json(
            os.path.join(self.cache_dir, "110.dynamic-html", "config.json"),
            {
                "aws": {
                    "python": {
                        "code_package": {"3.9": {"x64": {"location": "code"}}},
                        "containers": {},
                        "functions": {
                            "sebs-abc123-110.dynamic-html-python-3.9-x64": {
                                "name": "sebs-abc123-110.dynamic-html-python-3.9-x64",
                                "hash": "deadbeef",
                                "triggers": [
                                    {"type": "library"},
                                    {
                                        "type": "http",
                                        "url": "https://abc123.execute-api."
                                        "us-east-1.amazonaws.com/inspect",
                                        "implementation": "api_gateway",
                                    },
                                ],
                            }
                        },
                    },
                    "storage": {"sebs-benchmarks-abc123": {}},
                    "nosql": {"sebs-table-abc123": {}},
                }
            },
        )

    def tearDown(self) -> None:
        """Remove the temporary cache directory."""
        self._tmp.cleanup()

    def test_deployed_benchmarks(self) -> None:
        """Deployed benchmark rows expose platform, packaging, and triggers."""
        cache = Cache(self.cache_dir)
        rows = cache.get_deployed_benchmarks()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["benchmark"], "110.dynamic-html")
        self.assertEqual(row["platform"], "aws")
        self.assertEqual(row["language"], "python")
        self.assertEqual(row["packaging"], "code_package")
        self.assertEqual(len(row["functions"]), 1)
        self.assertEqual(row["triggers"], ["http", "library"])
        self.assertEqual(row["storage"], ["sebs-benchmarks-abc123"])
        self.assertEqual(row["nosql"], ["sebs-table-abc123"])
        # The HTTP trigger URL is surfaced both per-function and aggregated.
        self.assertEqual(
            row["urls"],
            ["https://abc123.execute-api.us-east-1.amazonaws.com/inspect"],
        )
        func = row["function_details"][0]
        http = [t for t in func["trigger_details"] if t["type"] == "http"][0]
        self.assertEqual(
            http["url"],
            "https://abc123.execute-api.us-east-1.amazonaws.com/inspect",
        )
        self.assertEqual(http["implementation"], "api_gateway")

    def test_deployed_benchmarks_filter(self) -> None:
        """Filtering by a platform with no entries yields an empty list."""
        cache = Cache(self.cache_dir)
        self.assertEqual(cache.get_deployed_benchmarks("gcp"), [])

    def test_allocated_resources(self) -> None:
        """Allocated resources expose ids, buckets, region, and ports."""
        cache = Cache(self.cache_dir)
        allocated = cache.get_allocated_resources()

        self.assertEqual(allocated["aws"]["resources_id"], "abc123")
        self.assertEqual(allocated["aws"]["region"], "us-east-1")
        self.assertEqual(len(allocated["aws"]["storage_buckets"]), 2)
        self.assertEqual(allocated["aws"]["allocated_ports"], [])

        self.assertEqual(allocated["local"]["resources_id"], "local42")
        self.assertEqual(allocated["local"]["allocated_ports"], [9000, 9001])

    def test_allocated_resources_filter(self) -> None:
        """Filtering allocated resources returns only the requested platform."""
        cache = Cache(self.cache_dir)
        allocated = cache.get_allocated_resources("aws")
        self.assertEqual(list(allocated.keys()), ["aws"])

    def test_allocated_resources_ports_only(self) -> None:
        """A local entry with only allocated ports is still reported."""
        cache = Cache(self.cache_dir)
        allocated = cache.get_allocated_resources("local")
        local = allocated["local"]
        # local42 has no buckets, only ports - it must remain visible.
        self.assertEqual(local["storage_buckets"], {})
        self.assertEqual(local["allocated_ports"], [9000, 9001])

    def test_allocated_resources_azure_classes(self) -> None:
        """Azure resource classes (group, accounts, NoSQL) are surfaced."""
        cache = Cache(self.cache_dir)
        allocated = cache.get_allocated_resources("azure")
        azure = allocated["azure"]
        self.assertEqual(azure["resources_id"], "az777")
        self.assertEqual(azure["region"], "westeurope")
        self.assertEqual(azure["resource_group"], "sebs_resource_group_az777")
        self.assertEqual(azure["storage_accounts"], ["sebsstorageaz777"])
        self.assertEqual(azure["nosql"], {"account_name": "sebs-cosmos-az777"})

    def test_inspection_is_read_only(self) -> None:
        """Reading and mutating the results never touches cache state."""
        cache = Cache(self.cache_dir)
        self.assertFalse(cache.config_updated)

        allocated = cache.get_allocated_resources("aws")
        cache.get_deployed_benchmarks("aws")
        # Reads must not flag the cache as dirty (which would trigger a
        # write-back on shutdown()).
        self.assertFalse(cache.config_updated)

        # The returned structure must be detached from cached_config: mutating
        # it must not leak back into the in-memory cache.
        allocated["aws"]["storage_buckets"]["INJECTED"] = "should-not-leak"
        allocated["aws"]["allocated_ports"].append(65535)
        live = cache.cached_config["aws"]["resources"]
        self.assertNotIn("INJECTED", live.get("storage_buckets", {}))
        self.assertNotIn(65535, live.get("allocated_ports", []))
        self.assertFalse(cache.config_updated)


if __name__ == "__main__":
    unittest.main()

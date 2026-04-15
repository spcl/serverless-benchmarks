# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
from __future__ import annotations

import tempfile
import unittest
from typing import TYPE_CHECKING, cast

import sebs
from sebs.faas.function import Trigger

if TYPE_CHECKING:
    import sebs.aws


class AWSFunctionURL(unittest.TestCase):
    """Integration tests for AWS Lambda Function URLs.

    Tests Function URL creation, invocation, caching, and cleanup.
    A single deployment client and benchmark are shared across all tests
    to avoid redundant Docker builds and resource initialization.
    """

    BENCHMARK_NAME = "110.dynamic-html"
    RESOURCE_PREFIX = "unit"

    BASE_CONFIG = {
        "deployment": {
            "name": "aws",
            "aws": {
                "region": "us-east-1",
                "resources": {
                    "use-function-url": True,
                    "function-url-auth-type": "NONE",
                },
            },
        },
        "experiments": {
            "deployment": "aws",
            "runtime": {"language": "python", "version": "3.9"},
            "update_code": False,
            "update_storage": False,
            "download_results": False,
            "architecture": "x64",
            "container_deployment": False,
        },
    }

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.client = sebs.SeBS(cls.tmp_dir.name, cls.tmp_dir.name)

        # Shared Python deployment client and benchmark
        cls.deployment_client = cls.client.get_deployment(cls.BASE_CONFIG)
        cls.deployment_client.initialize(resource_prefix=cls.RESOURCE_PREFIX)
        cls.experiment_config = cls.client.get_experiment_config(cls.BASE_CONFIG["experiments"])
        cls.benchmark = cls.client.get_benchmark(
            cls.BENCHMARK_NAME, cls.deployment_client, cls.experiment_config
        )
        cls.bench_input = cls.benchmark.prepare_input(
            system_resources=cls.deployment_client.system_resources, size="test"
        )

    @classmethod
    def tearDownClass(cls):

        cls.deployment_client.cleanup_resources(dry_run=False)

        # Shut down deployment client (stops containers) before removing temp dir
        if hasattr(cls, "deployment_client"):
            cls.deployment_client.shutdown()
        cls.tmp_dir.cleanup()

    def _get_function(self, suffix: str) -> sebs.aws.LambdaFunction:
        """Create/get a function with the given suffix appended to the default name."""
        name = "{}-{}".format(self.deployment_client.default_function_name(self.benchmark), suffix)
        return self.deployment_client.get_function(self.benchmark, name)

    def _invoke_sync(self, func: sebs.aws.LambdaFunction, func_input: dict):
        """Helper method to invoke function via Function URL and verify response."""
        triggers = func.triggers(Trigger.TriggerType.HTTP)
        self.assertGreater(len(triggers), 0, "No HTTP triggers found on function")
        ret = triggers[0].sync_invoke(func_input)
        self.assertFalse(ret.stats.failure)
        self.assertTrue(ret.request_id)
        self.assertGreater(ret.times.client, ret.times.benchmark)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_create_function_url_python(self):
        """Test Function URL creation with Python runtime and auth_type=NONE."""
        func = self._get_function("func-url")
        self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)

        all_triggers = func.triggers(Trigger.TriggerType.HTTP)
        self.assertGreater(len(all_triggers), 0)

        function_url_trigger = all_triggers[0]
        from sebs.aws.triggers import HTTPTrigger

        self.assertIsInstance(function_url_trigger, HTTPTrigger)
        self.assertTrue(function_url_trigger.uses_function_url)
        self.assertFalse(function_url_trigger.uses_api_gateway)
        self.assertTrue(function_url_trigger.url)
        self.assertTrue(function_url_trigger.url.startswith("https://"))

    def test_invoke_function_url_python(self):
        """Test function invocation via Function URL with Python runtime."""
        func = self._get_function("func-url")
        self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)
        self._invoke_sync(func, self.bench_input)

    def test_function_url_caching(self):
        """Test that Function URLs are cached and reused properly."""
        func = self._get_function("func-url")
        self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)
        first_url = func.triggers(Trigger.TriggerType.HTTP)[0].url

        # Get function again — should use cached Function URL
        func2 = self._get_function("func-url")
        self.deployment_client.create_trigger(func2, Trigger.TriggerType.HTTP)
        second_url = func2.triggers(Trigger.TriggerType.HTTP)[0].url

        self.assertEqual(first_url, second_url)

    def test_function_url_cleanup(self):
        """Test that Function URLs are deleted during cleanup."""
        func = self._get_function("func-url")
        self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)
        func_url = func.triggers(Trigger.TriggerType.HTTP)[0].url
        self.assertTrue(func_url)

        # Dry run first to verify detection
        cleanup_result = self.deployment_client.cleanup_resources(dry_run=True)
        self.assertIn("Function URLs", cleanup_result)
        self.assertEqual(len(cleanup_result["Function URLs"]), 1)
        self.assertEqual(cleanup_result["Function URLs"][0], func_url)

    def test_api_gateway_still_works(self):
        """Test that API Gateway triggers still work alongside Function URLs.

        Verifies:
        1. A single function can have both API Gateway and Function URL triggers
        2. Both trigger types are distinct HTTPTrigger instances
        3. Both triggers work with invocation
        """
        from sebs.aws.triggers import HTTPTrigger

        # Save original config
        original_use_function_url = self.deployment_client.config.resources.use_function_url

        try:
            func = self._get_function("dual-func-url")

            http_triggers = func.triggers(Trigger.TriggerType.HTTP)

            # Create API Gateway trigger first
            self.deployment_client.config.resources.use_function_url = False
            self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)

            # Add Function URL trigger to the same function
            self.deployment_client.config.resources.use_function_url = True
            self.deployment_client.create_trigger(func, Trigger.TriggerType.HTTP)

            # Verify we have 2 HTTP triggers
            http_triggers = func.triggers(Trigger.TriggerType.HTTP)
            self.assertEqual(len(http_triggers), 2)

            # Find each trigger type
            api_gw_trigger = None
            func_url_trigger = None

            for trigger in http_triggers:
                self.assertIsInstance(trigger, HTTPTrigger)
                trigger_aws = cast(sebs.aws.triggers.HTTPTrigger, trigger)
                if trigger_aws.uses_api_gateway:
                    api_gw_trigger = trigger
                elif trigger_aws.uses_function_url:
                    func_url_trigger = trigger

            # Verify both types exist
            self.assertIsNotNone(api_gw_trigger, "API Gateway trigger not found")
            self.assertIsNotNone(func_url_trigger, "Function URL trigger not found")

            # Verify API Gateway trigger properties
            self.assertTrue(api_gw_trigger.uses_api_gateway)
            self.assertFalse(api_gw_trigger.uses_function_url)
            self.assertTrue(api_gw_trigger.url.startswith("https://"))

            # Verify Function URL trigger properties
            self.assertTrue(func_url_trigger.uses_function_url)
            self.assertFalse(func_url_trigger.uses_api_gateway)
            self.assertTrue(func_url_trigger.url.startswith("https://"))

            # Verify different URLs
            self.assertNotEqual(api_gw_trigger.url, func_url_trigger.url)

            # Test invocation via both triggers
            ret_api_gw = api_gw_trigger.sync_invoke(self.bench_input)
            self.assertFalse(ret_api_gw.stats.failure)

            ret_func_url = func_url_trigger.sync_invoke(self.bench_input)
            self.assertFalse(ret_func_url.stats.failure)

        finally:
            # Restore original config
            self.deployment_client.config.resources.use_function_url = original_use_function_url


if __name__ == "__main__":
    unittest.main()

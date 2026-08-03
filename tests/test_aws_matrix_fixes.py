#!/usr/bin/env python3
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock

from sebs.aws.aws import AWS
from sebs.aws.config import AWSResources
from sebs.benchmark import BenchmarkConfig
from sebs.faas.function import ExecutionResult
from sebs.utils import LoggingHandlers


ROOT = Path(__file__).resolve().parents[1]


class AWSMatrixFixesTest(unittest.TestCase):
    def test_aws_report_parser_tolerates_application_log_fields(self):
        request_id = "1ebf703c-b814-4eb8-b26e-788f53d5e328"
        log = (
            f"START RequestId: {request_id} Version: $LATEST\n"
            f"2026-08-02T09:33:20.853Z\t{request_id}\tERROR\t"
            "(node:8) [DEP0040] DeprecationWarning: The `punycode` module is deprecated.\n"
            f"END RequestId: {request_id}\n"
            f"REPORT RequestId: {request_id}\tDuration: 9467.75 ms\t"
            "Billed Duration: 10014 ms\tMemory Size: 128 MB\t"
            "Max Memory Used: 112 MB\tInit Duration: 546.19 ms\n"
        )
        result = ExecutionResult()

        self.assertEqual(AWS.parse_aws_report(log, result), request_id)
        self.assertEqual(result.request_id, request_id)
        self.assertEqual(result.provider_times.execution, 9467750)
        self.assertEqual(result.provider_times.initialization, 546190)
        self.assertEqual(result.stats.memory_used, 112.0)
        self.assertEqual(result.billing.billed_time, 10014)
        self.assertEqual(result.billing.memory, 128)

    def test_new_default_lambda_role_receives_dynamodb_access(self):
        resources = AWSResources()
        resources.region = "us-east-1"
        iam_client = Mock()
        iam_client.get_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/sebs-lambda-role"}
        }
        session = Mock()
        session.client.return_value = iam_client

        resources.lambda_role(session)

        self.assertEqual(
            iam_client.put_role_policy.call_args.kwargs["RoleName"], "sebs-lambda-role"
        )
        self.assertEqual(
            iam_client.put_role_policy.call_args.kwargs["PolicyName"],
            "sebs-dynamodb-access",
        )
        policy = json.loads(iam_client.put_role_policy.call_args.kwargs["PolicyDocument"])
        self.assertEqual(
            policy["Statement"][0]["Action"],
            ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
        )
        self.assertEqual(
            policy["Statement"][0]["Resource"],
            "arn:aws:dynamodb:us-east-1:123456789012:table/sebs-benchmarks-*",
        )

        resources.lambda_role(session)
        self.assertEqual(iam_client.put_role_policy.call_count, 1)

    def test_configured_or_cached_lambda_role_is_not_modified(self):
        role_arn = "arn:aws:iam::123456789012:role/sebs-lambda-role"
        cases = (
            ({"lambda-role": role_arn, "resources": {}}, None),
            ({}, {"resources": {"lambda-role": role_arn}}),
        )
        for config, cached_config in cases:
            with self.subTest(config=config, cached_config=cached_config):
                cache = Mock()
                cache.get_config.return_value = cached_config
                resources = AWSResources.deserialize(config, cache, LoggingHandlers())
                session = Mock()

                self.assertEqual(resources.lambda_role(session), role_arn)
                session.client.assert_not_called()

    def test_411_is_container_only_on_aws(self):
        with (ROOT / "benchmarks/400.inference/411.image-recognition/config.json").open() as f:
            config = BenchmarkConfig.deserialize(json.load(f))

        self.assertFalse(config.supports_system_variant("aws", "package"))
        self.assertTrue(config.supports_system_variant("aws", "container"))
        self.assertTrue(config.supports_system_variant("local", "package"))

    def test_igraph_root_parent_conventions_validate_equally(self):
        module = runpy.run_path(str(ROOT / "benchmarks/500.scientific/503.graph-bfs/input.py"))
        validate_output = module["validate_output"]
        result = [list(range(10)), [0, 1, 10], [0] * 10]

        self.assertIsNone(
            validate_output(None, {"size": 10, "seed": 42}, {"result": result}, "python")
        )
        result[2][0] = 7
        self.assertIn(
            "checksum mismatch",
            validate_output(None, {"size": 10, "seed": 42}, {"result": result}, "python"),
        )

    def test_python_310_uses_the_wheel_compatible_dna_pins(self):
        requirements = ROOT / "benchmarks/500.scientific/504.dna-visualisation/python"
        self.assertEqual(
            (requirements / "requirements.txt.3.10").read_text(),
            (requirements / "requirements.txt.3.11").read_text(),
        )


if __name__ == "__main__":
    unittest.main()

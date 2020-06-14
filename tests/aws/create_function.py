import os
import tempfile
import unittest
import zipfile
from typing import List

import sebs


class AWSCreateFunction(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.client = sebs.SeBS(self.tmp_dir.name)

    def check_function(
        self, language: str, func: sebs.aws.LambdaFunction, files: List[str]
    ):
        filename, file_extension = os.path.splitext(func.code_package)
        self.assertEqual(file_extension, ".zip")

        # check zip file contents
        with zipfile.ZipFile(func.code_package) as package:
            package_files = package.namelist()
            for package_file in files:
                self.assertIn(package_file, package_files)

    def create_function(
        self, language: str, benchmark_name: str, files: List[str], config: dict
    ):
        deployment_client = self.client.get_deployment(config["deployment"])
        deployment_client.initialize()
        self.assertIsInstance(deployment_client, sebs.AWS)
        experiment_config = self.client.get_experiment(config["experiments"])

        benchmark = self.client.get_benchmark(
            benchmark_name, self.tmp_dir.name, deployment_client, experiment_config
        )
        self.assertFalse(benchmark.is_cached)
        self.assertFalse(benchmark.is_cached_valid)

        # generate default variant
        func = deployment_client.get_function(benchmark)
        timestamp = os.path.getmtime(benchmark.code_location)
        self.assertIsInstance(func, sebs.aws.LambdaFunction)
        self.check_function(language, func, files)
        self.assertTrue(benchmark.is_cached)
        self.assertTrue(benchmark.is_cached_valid)

        # use cached version
        benchmark = self.client.get_benchmark(
            benchmark_name, self.tmp_dir.name, deployment_client, experiment_config
        )
        self.assertTrue(benchmark.is_cached)
        self.assertTrue(benchmark.is_cached_valid)
        func = deployment_client.get_function(benchmark)
        current_timestamp = os.path.getmtime(benchmark.code_location)
        self.assertIsInstance(func, sebs.aws.LambdaFunction)
        self.check_function(language, func, files)
        # package code has not been rebuilt
        self.assertEqual(timestamp, current_timestamp)

        # force rebuild of cached version
        experiment_config.update_code = True
        benchmark = self.client.get_benchmark(
            benchmark_name, self.tmp_dir.name, deployment_client, experiment_config
        )
        self.assertTrue(benchmark.is_cached)
        self.assertFalse(benchmark.is_cached_valid)
        func = deployment_client.get_function(benchmark)
        current_timestamp = os.path.getmtime(benchmark.code_location)
        self.assertIsInstance(func, sebs.aws.LambdaFunction)
        self.check_function(language, func, files)
        # package should have been rebuilt
        self.assertLess(timestamp, current_timestamp)

        # wrong language version - expect failure
        experiment_config.runtime.version = "1.0"
        with self.assertRaises(Exception) as failure:
            benchmark = self.client.get_benchmark(
                benchmark_name, self.tmp_dir.name, deployment_client, experiment_config
            )
            func = deployment_client.get_function(benchmark)
        self.assertTrue(
            "Unsupported {} version 1.0".format(language) in str(failure.exception)
        )

    def test_create_function_python(self):
        config = {
            "deployment": {"name": "aws", "region": "us-east-1"},
            "experiments": {
                "runtime": {"language": "python", "version": "3.6"},
                "update_code": False,
                "update_storage": False,
                "download_results": False,
            },
        }
        benchmark = "110.dynamic-html"
        self.create_function(
            "python",
            benchmark,
            ["handler.py", "function/storage.py", "requirements.txt"],
            config,
        )

    def test_create_function_nodejs(self):
        config = {
            "deployment": {"name": "aws", "region": "us-east-1"},
            "experiments": {
                "runtime": {"language": "nodejs", "version": "10.x"},
                "update_code": False,
                "update_storage": False,
                "download_results": False,
            },
        }
        benchmark = "110.dynamic-html"
        self.create_function(
            "nodejs",
            benchmark,
            ["handler.js", "function/storage.js", "package.json"],
            config,
        )

    def tearDown(self):
        # FIXME: remove created functions
        pass

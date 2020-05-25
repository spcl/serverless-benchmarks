import os
import tempfile
import unittest
import zipfile
from typing import List

import sebs

class AWSUnitTest(unittest.TestCase):

    def setUp(self):
        config = {
	    "deployment": {
		"name": "aws",
		"region": "us-east-1"
	    }
  	}
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.client = sebs.SeBS(self.tmp_dir.name)

    def check_function(self, language: str, func: sebs.aws.LambdaFunction, files: List[str]):

        filename, file_extension = os.path.splitext(func.code_package)
        self.assertEqual(file_extension, '.zip')
        
        # check zip file contents
        with zipfile.ZipFile(func.code_package) as package:
            package_files = package.namelist()
            for package_file in files:
                self.assertIn(package_file, package_files)


    def create_function(self, language: str, benchmark: str, files: List[str], config: dict):
        deployment_client = self.client.get_deployment(
            config["deployment"]
        )
        self.assertIsInstance(deployment_client, sebs.AWS)
        experiment_config = self.client.get_experiment(config["experiments"])

        benchmark = self.client.get_benchmark(benchmark, self.tmp_dir.name, deployment_client, experiment_config)

        # generate default variant
        func = deployment_client.get_function(benchmark)
        self.assertIsInstance(func, sebs.aws.LambdaFunction)
        self.check_function(language, func, files)

        # use cached version
        #func = deployment_client.get_function(benchmark)
        #self.assertIsInstance(func, sebs.aws.LambdaFunction)
        #self.check_function(language, func, files)

        #TODO: force rebuild of cached version
        #TODO: wrong language version

    def test_create_function_python(self):
        config = {
	    "deployment": {
		"name": "aws",
		"region": "us-east-1"
	    },
            "experiments": {
                "runtime": {
                    "language": "python",
                    "version": "3.6"
                },
                "update_code": "false",
                "update_storage": "false",
                "download_results": "false"
            }
  	}
        benchmark = "110.dynamic-html"
        self.create_function("python", benchmark, ['handler.py', 'function/storage.py', 'requirements.txt'], config)

    def test_create_function_nodejs(self):
        config = {
	    "deployment": {
		"name": "aws",
		"region": "us-east-1"
	    },
            "experiments": {
                "runtime": {
                    "language": "nodejs",
                    "version": "10.x"
                },
                "update_code": "false",
                "update_storage": "false",
                "download_results": "false"
            }
  	}
        benchmark = "110.dynamic-html"
        self.create_function("nodejs", benchmark, ['handler.js', 'function/storage.js', 'package.json'], config)


    def tearDown(self):
        pass

def run():
    runner = unittest.TextTestRunner()
    runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(AWSUnitTest))

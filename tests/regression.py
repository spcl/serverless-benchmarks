#!/usr/bin/env python3

import argparse
import logging
import os
import tempfile
import unittest
import testtools
import sys

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
sys.path.append(PROJECT_DIR)

import sebs

parser = argparse.ArgumentParser(description="Run tests.")
parser.add_argument("--deployment", choices=["aws", "azure", "local"], nargs="+")

benchmarks = [
    "110.dynamic-html",
    #"120.uploader",
    "210.thumbnailer"
]
tmp_dir = tempfile.TemporaryDirectory()
sebs.utils.configure_logging()
client = sebs.SeBS(tmp_dir.name)

args = parser.parse_args()
if not args.deployment:
    args.deployment = []

class TestSequenceMeta(type):

    def __init__(cls, name, bases, attrs, config, experiment_config):
        type.__init__(cls, name, bases, attrs)
        cls.config = config
        cls.experiment_config = experiment_config

    def __new__(mcs, name, bases, dict, config, experiment_config):

        def gen_test(benchmark_name):
            def test(self):
                deployment_client = client.get_deployment(self.config)
                logging.info(
                    f"Begin regression test of {benchmark_name} on "
                    f"{deployment_client.name()}"
                )
                deployment_client.initialize()
                experiment_config = client.get_experiment(self.experiment_config)
                benchmark = client.get_benchmark(
                    benchmark_name, tmp_dir.name, deployment_client, experiment_config
                )
                storage = deployment_client.get_storage(
                    replace_existing=experiment_config.update_storage
                )
                input_config = benchmark.prepare_input(storage=storage, size="test")
                func = deployment_client.get_function(
                    benchmark,
                    deployment_client.default_function_name(benchmark)
                )
                ret = func.triggers[0].sync_invoke(input_config)
                if ret.stats.failure:
                    raise RuntimeError(f"Test of {benchmark_name} failed!")
            return test

        for benchmark in benchmarks:
            test_name = "test_%s" % benchmark
            dict[test_name] = gen_test(benchmark)
        return type.__new__(mcs, name, bases, dict)

class AWSTestSequence(unittest.TestCase,
        metaclass=TestSequenceMeta,
        config = {
            "name": "aws",
            "region": "us-east-1"
        },
        experiment_config = {
            "update_code": False,
            "update_storage": False,
            "download_results": False,
            "runtime": {
              "language": "python",
              "version": "3.6"
            },
        }
    ):
    pass

    #def setUp(self):
    #    self.stream_handler = logging.StreamHandler(sys.stdout)
    #    logger.addHandler(self.stream_handler)

    #def tearDown(self):
    #    logger.removeHandler(self.stream_handler)

# https://stackoverflow.com/questions/22484805/a-simple-working-example-for-testtools-concurrentstreamtestsuite
class TracingStreamResult(testtools.StreamResult):
    all_correct: bool
    output = {}

    def __init__(self):
        self.all_correct = True
        self.success = set()
        self.failures = set()

    def status(self, *args, **kwargs):
        self.all_correct = self.all_correct and (kwargs["test_status"] in ["inprogress", "success"])
        test_name = kwargs["test_id"].split('_')[-1]
        if not kwargs["test_status"]:
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            #print('{0[test_id]}: {0[test_status]}'.format(kwargs))
            #print('{0[test_id]}: {1}'.format(kwargs, self.output[kwargs["test_id"]].decode()))
            self.failures.add(test_name)
        elif kwargs["test_status"] == "success":
            self.success.add(test_name)
            #logging.info('{0[test_id]}: {0[test_status]}'.format(kwargs))


suite = unittest.TestSuite()
if "aws" in args.deployment:
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequence))
tests = []
for case in suite:
    for test in case:
        tests.append(test)
concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((test, None) for test in tests))
result = TracingStreamResult()
result.startTestRun()
concurrent_suite.run(result)
result.stopTestRun()
print(f"Succesfully executed {len(result.success)} out of {len(tests)} functions")
for suc in result.success:
    print(f"- {suc}")
if len(result.failures):
    print(f"Failures when executing {len(result.failures)} out of {len(tests)} functions")
    for failure in result.failures:
        print(f"- {failure}")
sys.exit(not result.all_correct)

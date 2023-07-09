#!/usr/bin/env python3

import argparse
import json
import logging
import os
import tempfile
import unittest
import testtools
import sys

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
sys.path.append(PROJECT_DIR)

import sebs
from sebs.faas.function import Trigger

parser = argparse.ArgumentParser(description="Run tests.")
parser.add_argument("--config", default=None, type=str)
parser.add_argument("--deployment", choices=["aws", "azure", "gcp"], nargs="+")
parser.add_argument("--language", choices=["python", "nodejs"], default="python")
parser.add_argument("--language-version", choices=["3.7", "3.8", "3.9", "10", "12", "14", "16"], default="3.7")

benchmarks_python = [
    "110.dynamic-html",
    "120.uploader",
    "210.thumbnailer",
    "220.video-processing",
    "311.compression",
    #"411.image-recognition",
    "501.graph-pagerank",
    "502.graph-mst",
    "503.graph-bfs",
    "504.dna-visualisation",
]
benchmarks_nodejs = [
    "110.dynamic-html",
    "120.uploader",
    "210.thumbnailer"
]
tmp_dir = tempfile.TemporaryDirectory()
client = sebs.SeBS("regression-cache", "regression-output")

args = parser.parse_args()
if not args.deployment:
    args.deployment = []


class TestSequenceMeta(type):
    def __init__(cls, name, bases, attrs, benchmarks, deployment_name, config, experiment_config):
        type.__init__(cls, name, bases, attrs)
        cls.benchmarks = benchmarks
        cls.deployment_name = deployment_name
        cls.config = config
        cls.experiment_config = experiment_config
        cls.language = None
        cls.language_version = None

    def __new__(mcs, name, bases, dict, benchmarks, deployment_name, config, experiment_config):
        def gen_test(benchmark_name):
            def test(self):

                deployment_client = client.get_deployment(
                    self.config,
                    os.path.join("regression-output", f"regression_test_{deployment_name}_{benchmark_name}_{self.language}_{self.language_version}.log")
                )
                logging.info(
                    f"Begin regression test of {benchmark_name} on " f"{deployment_client.name()}"
                )
                deployment_client.initialize()

                self.experiment_config["runtime"]["language"] = self.language
                self.experiment_config["runtime"]["version"] = self.language_version
                experiment_config = client.get_experiment_config(self.experiment_config)

                benchmark = client.get_benchmark(
                    benchmark_name, deployment_client, experiment_config
                )
                func = deployment_client.get_function(
                    benchmark, deployment_client.default_function_name(benchmark)
                )
                storage = deployment_client.get_storage(
                    replace_existing=experiment_config.update_storage
                )
                input_config = benchmark.prepare_input(storage=storage, size="test")

                trigger_type = Trigger.TriggerType.get("http")
                triggers = func.triggers(trigger_type)
                if len(triggers) == 0:
                    trigger = deployment_client.create_trigger(func, trigger_type)
                else:
                    trigger = triggers[0]
                ret = trigger.sync_invoke(input_config)
                if ret.stats.failure:
                    raise RuntimeError(f"Test of {benchmark_name} failed!")

            return test

        for benchmark in benchmarks:
            test_name = "test_%s" % benchmark
            dict[test_name] = gen_test(benchmark)
        return type.__new__(mcs, name, bases, dict)


class AWSTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    deployment_name="aws",
    config={"name": "aws", "aws": {"region": "us-east-1"}},
    experiment_config={
        "update_code": False,
        "update_storage": False,
        "download_results": False,
        "runtime": {"language": "python", "version": "3.7"},
    },
):
    pass

class AWSTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    deployment_name="aws",
    config={"name": "aws", "aws": {"region": "us-east-1"}},
    experiment_config={
        "update_code": False,
        "update_storage": False,
        "download_results": False,
        "runtime": {"language": "python", "version": "3.7"},
    },
):
    pass

class AzureTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    deployment_name="azure",
    config={"name": "azure", "azure": {"region": "westeurope"}},
    experiment_config={
        "update_code": False,
        "update_storage": False,
        "download_results": False,
        "runtime": {"language": "python", "version": "3.6"},
    },
):
    pass

class GCPTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    deployment_name="gcp",
    config={"name": "gcp", "gcp": {"region": "us-east-1"}},
    experiment_config={
        "update_code": False,
        "update_storage": False,
        "download_results": False,
        "runtime": {"language": "python", "version": "3.7"},
    },
):
    pass

class GCPTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    deployment_name="gcp",
    config={"name": "gcp", "gcp": {"region": "us-east-1"}},
    experiment_config={
        "update_code": False,
        "update_storage": False,
        "download_results": False,
        "runtime": {"language": "python", "version": "3.7"},
    },
):
    pass


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
        test_name = kwargs["test_id"].split("_")[-1]
        if not kwargs["test_status"]:
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            print("{0[test_id]}: {0[test_status]}".format(kwargs))
            print("{0[test_id]}: {1}".format(kwargs, self.output[kwargs["test_id"]].decode()))
            self.failures.add(test_name)
        elif kwargs["test_status"] == "success":
            self.success.add(test_name)


suite = unittest.TestSuite()
if "aws" in args.deployment:
    if args.language == "python":
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequencePython))
    elif args.language == "nodejs":
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequenceNodejs))
if "gcp" in args.deployment:
    if args.language == "python":
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequencePython))
    elif args.language == "nodejs":
        suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequenceNodejs))
if "azure" in args.deployment:
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequencePython))

tests = []
for case in suite:
    for test in case:
        test.language = args.language
        test.language_version = args.language_version

        if args.config is not None:
            test.config[test.deployment_name] = json.load(open(args.config, 'r'))['deployment'][test.deployment_name]

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

#!/usr/bin/env python3

import argparse
import os
import unittest
import testtools
import sys

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
sys.path.append(PROJECT_DIR)

parser = argparse.ArgumentParser(description="Run tests.")
parser.add_argument("--deployment", choices=["aws", "azure", "local"], nargs="+")

args = parser.parse_args()
if not args.deployment:
    args.deployment = []

# https://stackoverflow.com/questions/22484805/a-simple-working-example-for-testtools-concurrentstreamtestsuite
class TracingStreamResult(testtools.StreamResult):
    all_correct: bool
    output = {}

    def __init__(self):
        self.all_correct = True

    def status(self, *args, **kwargs):
        self.all_correct = self.all_correct and (kwargs["test_status"] in ["inprogress", "success"])
        if not kwargs["test_status"]:
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            print('{0[test_id]}: {0[test_status]}'.format(kwargs))
            print('{0[test_id]}: {1}'.format(kwargs, self.output[kwargs["test_id"]].decode()))
        elif kwargs["test_status"] == "success":
            print('{0[test_id]}: {0[test_status]}'.format(kwargs))

cases = []
if "aws" in args.deployment:
    from aws import suite
    for case in suite.suite():
        cases.append(case)
tests = []
for case in cases:
    for c in case:
        tests.append(c)
for test in tests:
    test.setUpClass()
concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((test, None) for test in tests))
result = TracingStreamResult()
result.startTestRun()
concurrent_suite.run(result)
result.stopTestRun()
for test in tests:
    test.tearDownClass()
sys.exit(not result.all_correct)

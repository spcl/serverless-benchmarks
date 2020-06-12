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

    def __init__(self):
        self.all_correct = False

    def status(self, *args, **kwargs):
        self.all_correct = self.all_correct and (kwargs[test_status] in ["inprogress", "success"])
        print('{0[test_id]}: {0[test_status]}'.format(kwargs))

cases = []
if "aws" in args.deployment:
    from aws import suite
    for case in suite.suite():
        cases.append(case)
concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((case, None) for case in cases))
result = TracingStreamResult()
result.startTestRun()
concurrent_suite.run(result)
result.stopTestRun()
sys.exit(result.all_correct)

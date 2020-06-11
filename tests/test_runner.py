#!/usr/bin/env python3

import argparse
import os
import unittest
import sys

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
sys.path.append(PROJECT_DIR)

parser = argparse.ArgumentParser(description="Run tests.")
parser.add_argument("--deployment", choices=["aws", "azure", "local"], nargs="+")

args = parser.parse_args()
if not args.deployment:
    args.deployment = []

return_value = True

runner = unittest.TextTestRunner()
if "aws" in args.deployment:
    from aws import suite
    return_value = return_value and not runner.run(suite.suite()).wasSuccessful()
sys.exit(return_value)

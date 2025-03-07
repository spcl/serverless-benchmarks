#!/usr/bin/env python3

import subprocess
from sys import argv, exit


def call(linter, source, args):
    return subprocess.call([linter, source] + args.split())


arg = argv[1]
print("Code formatting of with Black")
ret = call("black", arg, "--config .black.toml")

print("Check if Black has been applied correctly")
ret = ret | call("black", arg, "--check --config .black.toml")

print("flake8 linting")
ret = ret | call("flake8", arg, "--config=.flake8.cfg")

print("Check static typing")
ret = ret | call("mypy", arg, "--config-file=.mypy.ini")
exit(ret)

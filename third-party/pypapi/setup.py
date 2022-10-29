#!/usr/bin/env python
# encoding: UTF-8

import os
import subprocess

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py


class CustomBuildPy(build_py):

    def run(self):
        os.environ["CFLAGS"] = "%s -fPIC -Werror=format-truncation=0" % os.environ.get("CFLAGS", "")
        subprocess.call("cd papi/src/ && ./configure", shell=True)  # noqa
        subprocess.call("cd papi/src/ && make", shell=True)  # noqa
        build_py.run(self)


long_description = ""
if os.path.isfile("README.rst"):
    long_description = open("README.rst", "r").read()
elif os.path.isfile("README.md"):
    long_description = open("README.md", "r").read()


setup(
    name="python_papi",
    version="5.5.1.4",
    description="Python binding for the PAPI library",
    url="https://github.com/flozz/pypapi",
    license="WTFPL",

    long_description=long_description,
    keywords="papi perf performance",

    author="Fabien LOISON, Mathilde BOUTIGNY",
    # author_email="",

    packages=find_packages(),

    setup_requires=["cffi>=1.0.0"],
    install_requires=["cffi>=1.0.0"],

    cffi_modules=["pypapi/papi_build.py:ffibuilder"],

    cmdclass={
        "build_py": CustomBuildPy,
    },
)

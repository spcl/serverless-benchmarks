#!/usr/bin/env python3

import os
import re
import sys
from pathlib import Path
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

readme_path = os.path.join(here, "README.md")
with open(readme_path, encoding="utf-8") as f:
    long_description = f.read()

version_path = os.path.join(here, "sebs", "version.py")
version_dict = {}
with open(version_path) as f:
    exec(f.read(), version_dict)
__version__ = version_dict.get("__version__", "1.2.0")

# Core requirements (excluding dev tools)
install_requires = []
req_path = os.path.join(here, "requirements.txt")

# Dev tools to exclude from default install
dev_tools = ["flake8", "black", "mypy", "interrogate"]

if os.path.exists(req_path):
    with open(req_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments, empty lines, and dev tools
            if line and not line.startswith("#"):
                # Check if line starts with any dev tool name
                is_dev_tool = any(line.startswith(tool) for tool in dev_tools)
                # Also skip type stubs (types-*)
                if not is_dev_tool and not line.startswith("types-"):
                    install_requires.append(line)

# Add all platform-specific dependencies to default install
platform_files = ["requirements.aws.txt", "requirements.azure.txt",
                  "requirements.gcp.txt", "requirements.local.txt"]

for platform_file in platform_files:
    platform_path = os.path.join(here, platform_file)
    if os.path.exists(platform_path):
        with open(platform_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    install_requires.append(line)

# Legacy extras for backward compatibility (all dependencies now installed by default)
extras_require = {"aws": [], "azure": [], "gcp": [], "local": [], "openwhisk": [], "all": []}


def package_files(path, regexp):
    paths = []
    for path, directories, filenames in os.walk(path):
        for filename in filenames:
            if regexp.match(os.path.join(path, filename)):
                paths.append(os.path.join(os.path.pardir, path, filename))
    return paths


print(package_files("dockerfiles", re.compile("")))

setup(
    name="sebs",
    version=__version__,
    description="Serverless Benchmark Suite",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/spcl/serverless-benchmarks",
    author="Marcin Copik",
    author_email="marcin.copik@inf.ethz.ch",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
        "Topic :: System :: Benchmark",
        "Topic :: System :: Distributed Computing",
    ],
    keywords="serverless, faas, benchmark, lambda, azure-functions, cloud-computing",
    packages=find_packages(where=here, exclude=["tests", "tests.*"])
    + ["sebs.tools", "sebs.configs", "sebs.benchmarks", "sebs.dockerfiles"],
    package_dir={
        "sebs": "sebs",
        "sebs.tools": "tools",
        "sebs.configs": "configs",
        "sebs.dockerfiles": "dockerfiles",
        "sebs.benchmarks": "benchmarks",
    },
    python_requires=">=3.7",
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "sebs=sebs.cli:main",
        ],
    },
    package_data={
        "sebs.tools": ["create_azure_credentials.py"],
        "sebs.configs": ["systems.json"],
        "sebs.dockerfiles": package_files("dockerfiles", re.compile(".*.function")),
        "sebs.benchmarks": ["*", "*/*", "*/*/*", "*/*/*/*", "*/*/*/*/*"],
    },
    project_urls={
        "Bug Reports": "https://github.com/spcl/serverless-benchmarks/issues",
        "Source": "https://github.com/spcl/serverless-benchmarks",
    },
)

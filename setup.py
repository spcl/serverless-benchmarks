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

# Core requirements
install_requires = []
req_path = os.path.join(here, "requirements.txt")
if os.path.exists(req_path):
    with open(req_path, encoding="utf-8") as f:
        install_requires = [
            line.strip() for line in f if not line.startswith("#") and line.strip()
        ]
else:
    # Define core requirements manually if file not found
    install_requires = [
        "testtools>=2.4.0",
        "docker>=4.2.0",
        "tzlocal>=2.1",
        "requests",
        "pandas>=1.1.3",
        "numpy",
        "scipy",
        "pycurl>=7.43",
        "click>=7.1.2",
        "rich",
    ]

extras_require = {"aws": [], "azure": [], "gcp": [], "local": [], "openwhisk": []}

# Try to load platform-specific requirements from files
for platform in extras_require.keys():
    req_file = os.path.join(here, f"requirements.{platform}.txt")
    if os.path.exists(req_file):
        with open(req_file, encoding="utf-8") as f:
            extras_require[platform] = [
                line.strip() for line in f if not line.startswith("#") and line.strip()
            ]

# All platforms
extras_require["all"] = [
    req for platform_reqs in extras_require.values() for req in platform_reqs
]


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
        "sebs.configs": "config",
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

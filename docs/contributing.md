# Developer Guide

This guide provides essential information for developers contributing to SeBS.

## Table of Contents

- [Code Quality](#code-quality)
- [Docker Images](#docker-images)
- [Project Structure](#project-structure)

## Code Quality

SeBS enforces code quality through four tools:
* **Black** formats Python code to ensure consistent style across the codebase.
* **mypy** performs static type checking to catch type-related errors.
* **flake8** checks for style violations, unused imports, and potential bugs.
* **interrogate** checks that all classes and methods have Python docstrings.

Run `tools/linting.py sebs` to apply formatting and check code quality.

To use it, make sure that SeBS has been installed with development tools:

```bash
# with pip
pip install .[dev]

# with uv
uv sync --extra dev
```

## Docker Images

SeBS uses Docker images for building functions and running benchmarks:
* **build**: For installing dependencies in an environment matching the execution sandbox
* **run**: Language-based images for local function invocations
* **manage**: Management images (e.g., Azure CLI for resource management)
* **dependencies**: Special images for C++ dependencies (OpenCV, Boost, etc.)
* **function**: Benchmark-specific images for container deployments

### Docker Image Naming Convention

Infrastructure images follow this naming pattern:
```
{repository}:{type}.{platform}[.{language}[.{version}]]-{sebs-version}
```

Examples:
- `spcleth/serverless-benchmarks:build.aws.python.3.9-1.2.0`
- `spcleth/serverless-benchmarks:run.local.nodejs.16-1.2.0`
- `spcleth/serverless-benchmarks:manage.azure-1.2.0`

### Docker Image Build

Our CLI provides image management for all images except for `function` images,
as these are built and pushed as part of the benchmark deployment process:

```bash
# Build all images for all platforms
sebs docker build

# Build all images for a specific platform
sebs docker build --deployment aws

# Build images for a specific language and version
sebs docker build --deployment aws --language python --language-version 3.9

# Build specific image type
sebs docker build --deployment aws --language python --image-type build

# Build for specific architecture
sebs docker build --deployment aws --architecture x64

# Build C++ dependencies
sebs docker build --deployment local --language cpp --image-type dependencies --dependency-type opencv
```

### Pushing Images

Push locally-built infrastructure images to DockerHub (requires authentication):

```bash
# Push all images for a platform
sebs docker push --deployment aws
```

## Project Structure

```
sebs/
├── install.py                 # (Deprecated) Installation script
├── sebs/                      # Main Python package
│   ├── __init__.py
│   ├── sebs.py               # Core SeBS class
│   ├── cache.py              # Caching system of cloud resources
│   ├── cli.py                # Main CLI entry point
│   ├── benchmark.py          # Benchmark core class
│   ├── docker_builder.py     # Docker image build/push operations
│   ├── config.py             # SeBS configuration management
│   ├── faas/                 # FaaS platform abstractions
│   │   ├── system.py         # Base FaaS system
│   │   ├── function.py       # Functions and triggers
│   │   ├── storage.py        # Storage abstractions
│   │   └── container.py      # Platform Docker containers
│   ├── aws/                  # AWS Lambda implementation
│   ├── azure/                # Azure Functions implementation
│   ├── gcp/                  # Google Cloud Functions implementation
│   ├── openwhisk/            # OpenWhisk implementation
│   ├── local/                # Local Docker deployment
│   ├── storage/              # Storage implementations (Minio, ScyllaDB)
│   ├── experiments/          # Experiment implementations
│   └── regression.py         # Regression testing
├── benchmarks/               # Benchmark source code
│   ├── 000.microbenchmarks/  # Microbenchmarks (sleep, experiments) 
│   ├── 100.webapps/          # Web application benchmarks
│   ├── 200.multimedia/       # Multimedia processing benchmarks
│   ├── 300.utilities/        # Utility benchmarks
│   ├── 400.inference/        # ML inference benchmarks
│   ├── 500.scientific/       # Scientific computing benchmarks
│   └── wrappers/             # Platform-specific wrappers
├── benchmarks-data/          # Git submodule with input data
├── dockerfiles/              # Dockerfiles for all image types
│   ├── aws/
│   ├── azure/
│   ├── gcp/
│   ├── local/
│   └── openwhisk/
├── config/                   # Configuration files
│   ├── example.json          # Example configuration
│   └── systems.json          # System/platform definitions
├── tools/                    # Utility scripts
├── docs/                     # Documentation
```


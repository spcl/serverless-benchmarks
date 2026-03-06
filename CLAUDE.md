# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SeBS (Serverless Benchmark Suite) is a FaaS benchmarking suite that automatically builds, deploys, and measures serverless functions across commercial and open-source platforms. It supports AWS Lambda, Azure Functions, Google Cloud Functions, OpenWhisk, and local Docker-based execution.

## Essential Commands

### Installation

#### Package Install (Recommended for Users)
```bash
# Install from PyPI - includes all platform dependencies by default
pip install serverless-benchmarks

# Use sebs command
sebs --help

# Note: All platform dependencies (AWS, Azure, GCP, local) are installed by default.
# Legacy extras like [aws], [azure], [gcp], [all] are still accepted but have no effect.
```

#### Development Install (Git Clone)
```bash
# Option 1: Editable install (recommended) - installs all dependencies
pip install -e .
sebs --help

# Option 2: Legacy install.py script - selective platform installation
./install.py --aws --azure --gcp --openwhisk --local
. python-venv/bin/activate
python sebs.py --help

# Note: With editable install, all platform dependencies are installed by default.
# The install.py script is maintained for backward compatibility and selective installs.
```

#### Editable Install (Contributors)
```bash
# All platform dependencies installed by default
pip install -e .

# With development tools (linting, type checking, etc.)
pip install -e .[dev]

sebs --help
```

### Running Benchmarks
```bash
# Invoke a single benchmark
./sebs.py benchmark invoke <benchmark-name> <input-size> --config configs/example.json --deployment <platform> [--verbose]

# Example: Run dynamic-html on AWS with test input
./sebs.py benchmark invoke 110.dynamic-html test --config configs/example.json --deployment aws --verbose

# Force code/storage updates
./sebs.py benchmark invoke <benchmark-name> <input-size> --config configs/example.json --deployment <platform> --update-code --update-storage
```

### Regression Testing
```bash
# Run all benchmarks on a platform
./sebs.py benchmark regression test --config configs/example.json --deployment <platform>

# Run regression on single benchmark
./sebs.py benchmark regression test --config configs/example.json --deployment aws --benchmark-name 120.uploader
```

### Experiments
```bash
# Run an experiment (e.g., perf-cost)
./sebs.py experiment invoke <experiment-name> --config configs/example.json --deployment <platform>

# Process experiment results to get cloud metrics
./sebs.py experiment process <experiment-name> --config configs/example.json --deployment <platform>
```

### Local Deployment
```bash
# Start storage instance
./sebs.py storage start all configs/storage.json --output-json out_storage.json

# Merge storage config with deployment config
jq '.deployment.local.storage = input' configs/example.json out_storage.json > configs/local_deployment.json

# Start local containers
./sebs.py local start <benchmark-name> <input-size> out_benchmark.json --config configs/local_deployment.json --deployments 1 --remove-containers --architecture=x64

# Invoke local function with curl
curl $(jq -rc ".functions[0].url" out_benchmark.json) \
    --request POST \
    --data $(jq -rc ".inputs[0]" out_benchmark.json) \
    --header 'Content-Type: application/json'

# Stop containers
./sebs.py local stop out_benchmark.json
./sebs.py storage stop all out_storage.json
```

### Testing
```bash
# Run tests for specific deployment
./tests/test_runner.py --deployment aws
```

### Code Quality
```bash
# Format code with Black (line length: 100)
black <file.py>

# Run type checking with mypy
mypy <file.py>

# Lint with flake8
flake8 <file.py>
```

## High-Level Architecture

### Core Components

**CLI Entry Point** (`sebs.py`):
- Main CLI using Click framework
- Commands: `benchmark`, `experiment`, `local`, `storage`
- Creates `SeBS` and `FaaS System` instances to orchestrate deployments

**SeBS Library** (`sebs/`):
- `sebs/sebs.py` - Main `SeBS` class, entrypoint for all functionality
- `sebs/benchmark.py` - `Benchmark` and `BenchmarkConfig` classes encapsulating benchmark configuration
- `sebs/cache.py` - Local cache for functions and cloud resources
- `sebs/config.py` - Common configuration parameters
- `sebs/regression.py` - Regression test suite implementation
- `sebs/utils.py` - Serialization and logging utilities

**FaaS Abstraction Layer** (`sebs/faas/`):
- `system.py` - Abstract `System` class defining platform interface
- `storage.py` - Abstract `PersistentStorage` class for cloud storage
- `function.py` - `Function`, `Trigger`, and `ExecutionResult` classes
- `config.py` - Abstract `Credentials` and `Resources` interfaces

**Platform Implementations** (`sebs/{platform}/`):
- Each platform directory (`aws/`, `azure/`, `gcp/`, `openwhisk/`, `local/`) implements the FaaS interface
- Platform-specific code for function deployment, invocation, and metrics collection

**Experiments** (`sebs/experiments/`):
- Experiment implementations: `perf_cost.py`, `invocation_overhead.py`, `network_ping_pong.py`, `eviction_model.py`
- Base `Experiment` class in `experiment.py`
- Results handling in `result.py`

### Function Deployment Flow

**Code Package Deployment:**
1. Query cache for up-to-date build
2. Copy benchmark code to build location
3. Add platform-specific wrappers from `benchmarks/wrappers/{platform}/`
4. Add deployment packages (cloud SDKs, Minio SDK, etc.)
5. Install dependencies in Docker build container
6. Package code according to platform requirements
7. Deploy to cloud platform

**Docker Image Deployment** (OpenWhisk, AWS Lambda optional):
1. Query cache for up-to-date build
2. Prepare benchmark code with platform-specific dependencies
3. Build Docker image `function.{platform}.{benchmark}.{language}-{version}-{architecture}-{sebs-version}`
4. Push image to registry (ECR for AWS, DockerHub/custom for OpenWhisk)
5. Deploy function with image reference

### Benchmark Structure

Benchmarks are organized in `benchmarks/` with naming scheme `x.y.z` where:
- x = benchmark group (0=microbenchmarks, 100=webapps, 200=multimedia, 300=utilities, 400=inference, 500=scientific)
- y = benchmark ID within group
- z = benchmark version

Each benchmark contains:
- `config.json` - Timeout, memory, and supported languages
- `input.py` - Input generation logic (platform-independent)
- `{language}/function.{ext}` - Function handler implementation
- `{language}/requirements.txt` or `package.json` - Dependencies
- `{language}/init.sh` - Optional setup script for additional resources

**Wrappers** (`benchmarks/wrappers/`):
- Lightweight shims implementing cloud-specific APIs
- Platform-specific handler wrappers process cloud input and call benchmark function
- Platform-specific storage wrappers implement upload/download/list operations

### Key Design Principles

**Platform Independence:**
- Benchmarks written once, deployed everywhere
- Platform-specific code isolated to wrappers and FaaS implementations
- Single input generation script (`input.py`) for all language versions

**Caching Strategy:**
- Default cache directory: `cache/` (regression uses `regression-cache/`)
- Stores built code packages and cloud resource metadata
- Rebuilds triggered by source code changes or `--update-code` flag
- Cache does not support region changes - use new cache directory

**Build System:**
- Uses Docker "build images" to install dependencies in environment resembling cloud executor
- Separate build images per platform in `dockerfiles/{platform}/`
- C++ benchmarks use CMake configuration generation

**Trigger System:**
- Each `Function` exposes list of `Trigger` objects
- `Trigger` implementations provide `sync_invoke` and `async_invoke` methods
- HTTP invocation implemented generically using `pycurl`

## Important Platform Details

**AWS Lambda:**
- Supports x64 and arm64 architectures
- Code package or Docker image deployment
- Requires IAM role with Lambda and S3 permissions
- HTTP trigger via API Gateway (requires `AmazonAPIGatewayAdministrator`)

**Azure Functions:**
- Code package deployment only (no Docker image support)
- Requires service principal for non-interactive authentication
- Use `tools/create_azure_credentials` to create credentials

**Google Cloud Functions:**
- Code package deployment only
- Project-based resource organization

**OpenWhisk:**
- All functions deployed as Docker images (small code package size limit)
- Supports DockerHub or custom registry
- Still requires small zip package with main handler

**Local:**
- Uses Docker containers with HTTP server + language worker
- Minio for object storage, ScyllaDB for NoSQL
- Optional `pypapi` support for hardware counter profiling
- Memory measurements with `--measure-interval` flag

## Configuration Notes

- Main config: `configs/example.json`
- Credentials can be provided via environment variables or JSON config
- **Never commit credentials to version control** - SeBS erases credentials when saving results
- Platform-specific environment variables: `AWS_ACCESS_KEY_ID`, `AZURE_SECRET_APPLICATION_ID`, etc.
- Platform detection:
  - Package/editable install: Automatic detection via dependency imports (all platforms available by default)
  - Git clone with install.py: Uses `SEBS_WITH_{PLATFORM}` environment variables in venv activation script

## Adding New Components

**New Benchmark:**
1. Create directory `benchmarks/{group}.{category}/{id}.{name}/`
2. Add `config.json` with timeout, memory, languages
3. Implement `input.py` with `buckets_count()` and `generate_input()`
4. Add language implementations in `{language}/function.{ext}`
5. Add dependencies in `requirements.txt`/`package.json`
6. Optional: Add `init.sh` for additional resources

**New Platform:**
1. Implement `System` class from `sebs/faas/system.py`
2. Implement `PersistentStorage` class from `sebs/faas/storage.py`
3. Create platform-specific wrappers in `benchmarks/wrappers/{platform}/`
4. Add Dockerfile for build image in `dockerfiles/{platform}/`
5. Update CLI choices in `sebs.py`

**New Experiment:**
1. Create class inheriting from `sebs.experiments.experiment.Experiment`
2. Implement `run()` method with experiment logic
3. Add configuration schema to experiment config JSON
4. Register in experiments module

## Docker Images

Three types of Docker images:
- **build** - Install function dependencies (environment resembling cloud executor)
- **run** - Language-based images for local invocations
- **manage** - Management tools (e.g., Azure CLI)

Rebuild all images: `tools/build_docker_images.py`

## Important Warnings

- **Never use SeBS with sudo** - Docker daemon must be accessible without root
- **libcurl headers required** - `pycurl` needs development packages installed
- **Cache directory is region-specific** - Use new cache for different cloud regions
- **Benchmark data in separate repo** - `benchmarks-data` submodule from https://github.com/spcl/serverless-benchmarks-data

## Python Package Design

SeBS is designed to work in both **package install** (PyPI) and **git clone** modes:

### Package Structure
- **sebs/** - Main package code (including `sebs/config.py` module with `SeBSConfig` class)
- **benchmarks/** - Benchmark implementations (mapped to `sebs.benchmarks` in package)
- **dockerfiles/** - Dockerfile templates (mapped to `sebs.dockerfiles` in package)
- **configs/** - Configuration JSON files (mapped to `sebs.configs` in package)
- **tools/** - Utility scripts (mapped to `sebs.tools` in package)

### Dependency Management
- **All platform dependencies installed by default**: AWS (boto3), Azure (azure-storage-blob, azure-cosmos), GCP (google-cloud-*), and local (minio) dependencies are included in the base installation
- **Legacy extras**: `[aws]`, `[azure]`, `[gcp]`, `[local]`, `[all]` extras are maintained for backward compatibility but are now empty (all dependencies in base install)
- **Development extras**: `[dev]` includes linting, type checking, and testing tools

### Resource Manager
The `sebs/resource_manager.py` module handles path resolution for both modes:

**Git Clone Mode:**
- Resources accessed from repository root
- Benchmarks-data in `./benchmarks-data/`
- Cache in `./cache/` or `./regression-cache/`

**Package Install Mode:**
- Resources accessed from package installation
- Benchmarks-data auto-cloned to `~/.sebs/benchmarks-data/`
- Cache in `~/.sebs/cache/` or `~/.sebs/regression-cache/`

### Key Functions
- `get_resource_path(*paths)` - Get path to config/benchmarks/dockerfiles
- `get_benchmarks_data_path()` - Get path to benchmarks-data directory
- `ensure_benchmarks_data()` - Clone benchmarks-data if missing
- `get_cache_dir(use_regression)` - Get cache directory path

### Platform Detection (`has_platform`)
The `sebs.utils.has_platform(name)` function detects platform availability:
- **Environment variable check**: First checks `SEBS_WITH_{PLATFORM}` env var (for install.py compatibility)
- **Import check**: If env var not set, tries to import platform dependencies
- **Returns**: `True` if platform is available, `False` otherwise

This works across all installation modes:
- Package install: Detects via imports (all platforms available by default)
- Editable install: Detects via imports (all platforms available by default)
- Git clone with install.py: Uses environment variables
- Git clone without install.py: Detects via imports

### CLI Entry Points
- **Package install:** `sebs` command (from pyproject.toml entry_points)
- **Git clone:** `python sebs.py` or `./sebs.py` (backward compatibility wrapper)
- Both call `sebs.cli:main()` which validates benchmarks-data before running CLI commands

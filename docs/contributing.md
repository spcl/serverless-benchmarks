# Developer Guide

This guide provides essential information for developers contributing to SeBS.

## Table of Contents

- [Code Quality](#code-quality)
- [Approved Pull Request Tests](#approved-pull-request-tests)
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

## Approved Pull Request Tests

Maintainers with repository **write**, **maintain**, or **admin** access can
request regression tests directly from a pull request conversation, including
pull requests from forks. Review the changes, copy the full current head commit
SHA, and post one of these commands as a new comment:

```text
/test cloud <full-40-character-lowercase-head-SHA>
/test openwhisk <full-40-character-lowercase-head-SHA>
```

`cloud` runs the existing AWS/GCP/Azure matrix; `openwhisk` runs the existing
OpenWhisk matrix on kind. Each command must occupy the whole comment. Editing
an existing comment does not launch tests. Bot comments, ordinary issue comments,
and commands from users without repository write access are ignored.

The command authorizes execution of that specific commit. The controller checks
the author's current repository permissions and verifies that the PR is open,
targets `master`, and still has the specified head SHA. The dispatched workflow
checks the target again before starting. A later push requires a new review and
command; an earlier success remains attached only to the commit actually tested.

Results appear in the PR's status checks as `regression/cloud` or
`regression/openwhisk`, with a link to the run and its artifacts. For rejected
commands, inspect the **Run PR tests** request run in Actions. The same suites can
also be launched using **Actions → Run PR tests → Run workflow**, selecting branch
`master` and supplying the PR number, suite, and reviewed head SHA.

### Enabling and extending the commands

Merge `.github/workflows/pr-tests.yml`, its controller script, and the reusable
workflow changes into `master` first. Commands then work on already-open PRs;
the contributor does not need to rebase. The workflow token must be allowed to
dispatch Actions workflows and publish commit statuses. No personal access token
is needed. An environment approval configured on a regression job still applies.

The request and status jobs check out only the trusted workflow commit. The
regression jobs use workflow definitions from that same commit, check out the
approved PR SHA, and receive a read-only GitHub token. The cloud suite uses the
existing cloud secrets, so review the PR before issuing a command and use cloud
credentials restricted to regression resources. OpenWhisk receives no inherited
cloud secrets. PR runs disable the uv cache to avoid writing PR-controlled cache
contents into the default branch's cache scope.

To add a suite, extend the controller's explicit suite allowlist and command
parser, add a choice and a separate reusable-workflow job in `pr-tests.yml`, and
include that job's result in the reporting step. Keep workflow paths literal and
the approved checkout SHA explicit. Run the controller tests with:

```bash
node --test .github/scripts/pr-tests.test.cjs
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
- `spcleth/serverless-benchmarks:run.local.nodejs.20-1.2.0`
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

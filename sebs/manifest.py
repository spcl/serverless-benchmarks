# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Reproducibility manifest of an experiment run.

The manifest is a JSON document written to `<output_dir>/manifest.json`
at the end of every `benchmark invoke` and `experiment invoke`. It records
what was run: the SeBS source revision, how benchmarks were built, deployed
function configuration, inputs, and the host that drove the experiment.

Collection is passive and best-effort and may never cause a run to fail.

A build is described when the package is built and cached next to it,
so that runs reusing a cached package report the original build.
The manifest itself is assembled from end-of-run state.

The TypedDicts below are the schema; bump SCHEMA_VERSION on incompatible changes.
"""

import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, TypedDict, TypeVar, TYPE_CHECKING

from sebs.utils import JSONSerializer, get_benchmarks_data_path, get_project_root
from sebs.version import __version__

if TYPE_CHECKING:
    from sebs.benchmark import Benchmark
    from sebs.experiments.config import Config as ExperimentConfig
    from sebs.faas.system import System
    from sebs.sebs import SeBS

SCHEMA_VERSION = 1

T = TypeVar("T")


class BuilderImage(TypedDict):
    """Docker image in which the code package dependencies were installed."""

    name: str
    id: str
    repo_digests: List[str]


class Build(TypedDict):
    """How a code package or container was built."""

    built: str
    builder_image: Optional[BuilderImage]


class Input(TypedDict):
    """An input size prepared for a benchmark and the digest of its payload."""

    size: str
    payload_sha256: str


class BenchmarkEntry(TypedDict):
    """A benchmark used in the run."""

    name: str
    language: str
    language_version: str
    architecture: str
    variant: str
    system_variant: str
    source_sha256: str
    build: Optional[Build]
    inputs: List[Input]


class FunctionEntry(TypedDict):
    """A function invoked in the run."""

    name: str
    benchmark: str
    config: Any


class Source(TypedDict):
    """Revision of the SeBS sources and benchmark data."""

    revision: Optional[str]
    dirty: Optional[bool]
    diff_sha256: Optional[str]
    data_revision: Optional[str]


class Versions(TypedDict):
    """SeBS version and the versions of its system configuration."""

    sebs: str
    systems: str
    previous_systems: str


class Host(TypedDict):
    """The machine that drove the experiment."""

    platform: str
    machine: str
    python: str
    docker: Optional[str]


class Deployment(TypedDict):
    """Platform and region the functions were deployed to."""

    name: str
    # Platforms without regions, such as local, report None.
    region: Optional[str]


class Manifest(TypedDict):
    """The reproducibility manifest of a run."""

    schema_version: int
    created: str
    command: List[str]
    versions: Versions
    source: Source
    host: Host
    deployment: Deployment
    experiment: Dict[str, Any]
    benchmarks: List[BenchmarkEntry]
    functions: List[FunctionEntry]
    unavailable: Dict[str, str]


class Probes:
    """Runs best-effort probes and records why the failed ones are unavailable."""

    def __init__(self) -> None:
        """Start with no unavailable values."""
        self.unavailable: Dict[str, str] = {}

    def __call__(self, key: str, probe: Callable[[], T]) -> Optional[T]:
        """Run `probe`; on failure, record the reason under `key` and return None."""
        try:
            return probe()
        except Exception as e:
            self.unavailable[key] = f"{type(e).__name__}: {e}"
            return None


def git(directory: str, *args: str) -> str:
    """Run a git command in the repository rooted at `directory` and return its stdout.

    Fails if `directory` is not a repository root, e.g., for a pip-installed SeBS,
    instead of describing an enclosing repository.
    """
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": os.path.dirname(os.path.abspath(directory))}
    return subprocess.run(
        ["git", "-C", directory, *args],
        capture_output=True,
        check=True,
        timeout=10,
        text=True,
        env=env,
    ).stdout


def collect_source(probe: Probes) -> Source:
    """Git revisions and dirty state of the SeBS repository and benchmark data."""
    root = str(get_project_root())
    data_dir = str(get_benchmarks_data_path())
    diff = probe("source.diff", lambda: git(root, "diff", "HEAD"))
    return {
        "revision": probe("source.revision", lambda: git(root, "rev-parse", "HEAD").strip()),
        "dirty": bool(diff) if diff is not None else None,
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff is not None else None,
        "data_revision": probe(
            "source.data_revision", lambda: git(data_dir, "rev-parse", "HEAD").strip()
        ),
    }


def benchmark_entry(benchmark: "Benchmark") -> BenchmarkEntry:
    """Manifest entry of a benchmark: source hash, build, and inputs."""
    inputs: List[Input] = [
        {
            "size": size,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, cls=JSONSerializer).encode()
            ).hexdigest(),
        }
        for size, payload in benchmark.prepared_inputs.items()
    ]
    return {
        "name": benchmark.benchmark,
        "language": benchmark.language_name,
        "language_version": benchmark.language_version,
        "architecture": benchmark.architecture,
        "variant": benchmark.language_variant,
        "system_variant": benchmark.system_variant.serialize(),
        "source_sha256": benchmark.hash,
        "build": benchmark.build_info,
        "inputs": inputs,
    }


def experiment_entry(config: "ExperimentConfig", experiment: Optional[str]) -> Dict[str, Any]:
    """The run's experiment configuration, without the settings of experiments that did not run.

    Args:
        config: Experiment configuration of the run
        experiment: Name of the experiment, or None for a plain benchmark invocation
    """
    entry = config.serialize()
    entry["experiments"] = (
        {experiment: config.experiment_settings(experiment)} if experiment is not None else {}
    )
    return entry


def build_manifest(
    sebs_client: "SeBS",
    deployment_client: "System",
    experiment_config: "ExperimentConfig",
    experiment: Optional[str],
) -> Manifest:
    """Assemble the manifest from the state at the end of a run.

    Args:
        sebs_client: Top-level SeBS object, holding the global configuration and Docker client
        deployment_client: Platform client (e.g., AWS, local) that deployed the run's functions
        experiment_config: Experiment configuration of the run
        experiment: Name of the experiment, or None for a plain benchmark invocation
    """
    probe = Probes()
    source = collect_source(probe)

    benchmarks: Dict[int, "Benchmark"] = {}
    functions: List[FunctionEntry] = []
    for benchmark, function in deployment_client.used_functions:
        benchmarks[id(benchmark)] = benchmark
        functions.append(
            {
                "name": function.name,
                "benchmark": benchmark.benchmark,
                "config": function.config,
            }
        )

    docker_version = probe("host.docker", lambda: sebs_client.docker_client.version()["Version"])
    return {
        "schema_version": SCHEMA_VERSION,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": sys.argv[1:],
        "versions": {
            "sebs": __version__,
            "systems": sebs_client.config.version(),
            "previous_systems": sebs_client.config.previous_version(),
        },
        "source": source,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "docker": docker_version,
        },
        "deployment": {
            "name": deployment_client.name(),
            "region": deployment_client.config.region or None,
        },
        "experiment": experiment_entry(experiment_config, experiment),
        "benchmarks": [benchmark_entry(benchmark) for benchmark in benchmarks.values()],
        "functions": functions,
        "unavailable": probe.unavailable,
    }


def write_manifest(
    output_dir: str,
    sebs_client: "SeBS",
    deployment_client: "System",
    experiment_config: "ExperimentConfig",
    experiment: Optional[str],
) -> str:
    """Write `manifest.json` into the output directory and return its path."""
    manifest = build_manifest(sebs_client, deployment_client, experiment_config, experiment)
    path = os.path.join(output_dir, "manifest.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, cls=JSONSerializer)
    return path

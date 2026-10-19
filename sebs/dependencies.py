# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Locked Node.js dependencies of benchmarks.

The deployment wrappers of a benchmark need packages of their own, configured in
`packages` (always installed) and `module_packages` (installed for the benchmark's
modules, e.g., `storage`) of configs/systems.json. They share `node_modules` with the
benchmark, and npm has no optional dependency groups, so every Node.js source
directory, i.e., the benchmark's `nodejs/` and each variant directory with its own
package.json, has one lockfile per deployment: `package-lock.<deployment>.json` locks
the package.json with the deployment packages merged in.

`tools/lock_nodejs_benchmarks.py` generates the lockfiles. The build merges the same
package.json and verifies that the lockfile was generated from it.
"""

import json
import os
import shutil
from typing import Iterable, List

from sebs.config import SeBSConfig

# Fields of package.json that npm records in the root entry of the lockfile.
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def nodejs_package_json(
    package_json: dict, config: SeBSConfig, deployment: str, modules: Iterable[str]
) -> dict:
    """Return the package.json that a deployment installs for a benchmark.

    Args:
        package_json: The benchmark's package.json
        config: SeBS configuration with the deployment packages
        deployment: Name of the deployment
        modules: Modules used by the benchmark, e.g., `storage`

    Returns:
        dict: The package.json with the deployment packages merged in
    """
    packages = dict(config.deployment_packages(deployment, "nodejs"))
    module_packages = config.deployment_module_packages(deployment, "nodejs")
    for module in modules:
        packages.update(module_packages.get(module, {}))
    return {**package_json, "dependencies": {**package_json.get("dependencies", {}), **packages}}


def nodejs_lockfile_is_current(lockfile: str, package_json: dict) -> bool:
    """Check that a lockfile exists and was generated from a package.json.

    Args:
        lockfile: Path to the package-lock.json
        package_json: The parsed package.json

    Returns:
        bool: True if the lockfile records exactly the dependencies of the package.json
    """
    if not os.path.exists(lockfile):
        return False
    with open(lockfile) as f:
        root = json.load(f).get("packages", {}).get("", {})
    return all(root.get(field, {}) == package_json.get(field, {}) for field in DEPENDENCY_FIELDS)


def nodejs_source(language_dir: str, variant: str) -> str:
    """Return the source directory whose package.json and lockfiles a variant uses.

    Args:
        language_dir: The benchmark's `nodejs/` directory
        variant: Name of the language variant

    Returns:
        str: The variant directory if it has its own package.json, else `nodejs/`
    """
    variant_dir = os.path.join(language_dir, variant)
    if variant != "default" and os.path.exists(os.path.join(variant_dir, "package.json")):
        return variant_dir
    return language_dir


def nodejs_sources(language_dir: str) -> List[str]:
    """Return the Node.js source directories of a benchmark that are locked.

    Args:
        language_dir: The benchmark's `nodejs/` directory

    Returns:
        List[str]: `nodejs/` and every variant directory with its own package.json
    """
    variants = sorted(
        entry.path
        for entry in os.scandir(language_dir)
        if entry.is_dir() and nodejs_source(language_dir, entry.name) == entry.path
    )
    return [language_dir, *variants]


def nodejs_lockfile(source_dir: str, deployment: str) -> str:
    """Return the lockfile of a deployment in a Node.js source directory."""
    return os.path.join(source_dir, f"package-lock.{deployment}.json")


def add_nodejs_lockfile(
    output_dir: str,
    language_dir: str,
    variant: str,
    config: SeBSConfig,
    deployment: str,
    modules: Iterable[str],
) -> None:
    """Prepare the locked installation of a benchmark's Node.js dependencies.

    Merges the deployment packages into the package.json of the output directory
    and adds the deployment's lockfile as package-lock.json. A variant directory with
    its own package.json has its own lockfiles.

    Args:
        output_dir: Directory with the benchmark's package.json
        language_dir: The benchmark's `nodejs/` directory
        variant: Name of the language variant
        config: SeBS configuration with the deployment packages
        deployment: Name of the deployment
        modules: Modules used by the benchmark, e.g., `storage`

    Raises:
        RuntimeError: If the lockfile is missing or was not generated from the package.json
    """
    lockfile = nodejs_lockfile(nodejs_source(language_dir, variant), deployment)
    package_json_path = os.path.join(output_dir, "package.json")
    with open(package_json_path) as f:
        package_json = nodejs_package_json(json.load(f), config, deployment, modules)
    if not nodejs_lockfile_is_current(lockfile, package_json):
        # A patch variant changing package.json ends up here as well:
        # it must ship its own package.json to be locked.
        raise RuntimeError(f"{lockfile} is missing or stale; run tools/lock_nodejs_benchmarks.py")

    with open(package_json_path, "w") as f:
        json.dump(package_json, f, indent=2)
    shutil.copy2(lockfile, os.path.join(output_dir, "package-lock.json"))

"""Resource manager for SeBS package and git clone modes.

This module provides path resolution for resources (config files, benchmarks,
dockerfiles, tools) that works both in git clone mode and when installed as a
Python package.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

# Detect if running from installed package or git clone
_sebs_path = Path(__file__).parent
_is_git_clone = (_sebs_path.parent / ".git").exists()
_is_editable_install = not _is_git_clone and (_sebs_path.parent / ".git").exists()
_is_in_site_packages = "site-packages" in str(_sebs_path) or "dist-packages" in str(_sebs_path)

IS_PACKAGE_INSTALL = _is_in_site_packages and not _is_git_clone


def _is_package_install() -> bool:
    """Detect if running from installed package or git clone.

    Returns:
        True if running from installed package, False if git clone
    """
    return IS_PACKAGE_INSTALL


def get_project_root() -> Path:
    """Get project root directory.

    Returns:
        - For git clone: repository root
        - For package install: ~/.sebs/
    """
    if IS_PACKAGE_INSTALL:
        root = Path.home() / ".sebs"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).parent.parent


def get_resource_path(*path_parts: str) -> Path:
    """Get path to a resource (config, benchmarks, dockerfiles, tools).

    Args:
        *path_parts: Path components (e.g., "config", "systems.json")

    Returns:
        Path to the resource

    Examples:
        >>> get_resource_path("config", "systems.json")
        Path("/path/to/sebs/config/systems.json")

        >>> get_resource_path("benchmarks")
        Path("/path/to/sebs/benchmarks")
    """
    if IS_PACKAGE_INSTALL:
        # Use importlib.resources for package data
        try:
            from importlib.resources import files
        except ImportError:
            # Python 3.8 fallback
            import importlib.resources as resources
            from contextlib import contextmanager

            @contextmanager
            def files(package):
                yield resources.path(package, "")

        # Build path from package resources
        base = files("sebs")
        for part in path_parts:
            base = base / part

        # Convert to Path and return
        # For importlib.resources, we need to handle the Traversable object
        try:
            return Path(str(base))
        except Exception:
            # If the resource is in a subpackage, try that
            if path_parts:
                package = "sebs." + path_parts[0]
                try:
                    base = files(package)
                    for part in path_parts[1:]:
                        base = base / part
                    return Path(str(base))
                except Exception:
                    pass
            raise

    # Git clone mode: use relative paths from project root
    return get_project_root() / Path(*path_parts)


def get_benchmarks_data_path() -> Path:
    """Get path to benchmarks-data directory.

    Returns:
        - For git clone: ./benchmarks-data/
        - For package install: ~/.sebs/benchmarks-data/
    """
    if IS_PACKAGE_INSTALL:
        return Path.home() / ".sebs" / "benchmarks-data"
    return get_project_root() / "benchmarks-data"


def ensure_benchmarks_data() -> Path:
    """Ensure benchmarks-data exists, cloning if necessary.

    Returns:
        Path to benchmarks-data directory

    Raises:
        RuntimeError: If cloning fails
    """
    data_dir = get_benchmarks_data_path()

    # Check if data already exists and is not empty
    if data_dir.exists() and any(data_dir.iterdir()):
        return data_dir

    logger = logging.getLogger("sebs.resource_manager")

    # Create parent directory if needed
    data_dir.parent.mkdir(parents=True, exist_ok=True)

    # Determine clone method
    if IS_PACKAGE_INSTALL or not (get_project_root() / ".git").exists():
        # Package install or not a git repo: direct clone
        logger.info(f"Cloning benchmarks-data to {data_dir}...")
        try:
            result = subprocess.run(
                [
                    "git", "clone",
                    "https://github.com/spcl/serverless-benchmarks-data.git",
                    str(data_dir)
                ],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Benchmarks-data cloned successfully")
            return data_dir
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to clone benchmarks-data: {e.stderr}"
            ) from e
        except FileNotFoundError:
            raise RuntimeError(
                "git command not found. Please install git to use benchmarks-data"
            ) from None
    else:
        # Git clone mode: use submodule
        logger.info("Initializing benchmarks-data submodule...")
        try:
            result = subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive"],
                cwd=get_project_root(),
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Benchmarks-data submodule initialized successfully")
            return data_dir
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to initialize benchmarks-data submodule: {e.stderr}"
            ) from e


def get_cache_dir(use_regression: bool = False) -> Path:
    """Get the cache directory path.

    Args:
        use_regression: If True, return regression cache directory

    Returns:
        Path to cache directory
    """
    cache_name = "regression-cache" if use_regression else "cache"

    if IS_PACKAGE_INSTALL:
        cache_dir = Path.home() / ".sebs" / cache_name
    else:
        cache_dir = get_project_root() / cache_name

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# Module-level constants for backward compatibility
PROJECT_ROOT = get_project_root()
IS_GIT_CLONE = not IS_PACKAGE_INSTALL

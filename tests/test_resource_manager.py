"""Tests for the resource_manager module."""

import pytest
from pathlib import Path
from sebs.resource_manager import (
    _is_package_install,
    get_project_root,
    get_resource_path,
    get_benchmarks_data_path,
    get_cache_dir,
    IS_PACKAGE_INSTALL,
)


def test_package_detection():
    """Test package vs git clone detection."""
    is_package = _is_package_install()
    assert isinstance(is_package, bool)
    # In test environment, should be git clone mode
    assert is_package == IS_PACKAGE_INSTALL


def test_project_root_exists():
    """Test that project root path exists."""
    root = get_project_root()
    assert isinstance(root, Path)
    assert root.exists()
    assert root.is_dir()


def test_resource_path_config():
    """Test accessing config resources."""
    config_path = get_resource_path("config", "systems.json")
    assert isinstance(config_path, Path)
    assert config_path.exists()
    assert config_path.name == "systems.json"


def test_resource_path_benchmarks():
    """Test accessing benchmarks directory."""
    benchmarks_path = get_resource_path("benchmarks")
    assert isinstance(benchmarks_path, Path)
    assert benchmarks_path.exists()
    assert benchmarks_path.is_dir()


def test_resource_path_dockerfiles():
    """Test accessing dockerfiles directory."""
    dockerfiles_path = get_resource_path("dockerfiles")
    assert isinstance(dockerfiles_path, Path)
    assert dockerfiles_path.exists()
    assert dockerfiles_path.is_dir()


def test_benchmarks_data_path():
    """Test benchmarks-data path resolution."""
    data_path = get_benchmarks_data_path()
    assert isinstance(data_path, Path)
    # Path may or may not exist yet, but should be valid
    if IS_PACKAGE_INSTALL:
        assert str(data_path).startswith(str(Path.home() / ".sebs"))
    else:
        assert "benchmarks-data" in str(data_path)


def test_cache_dir():
    """Test cache directory creation."""
    cache_dir = get_cache_dir(use_regression=False)
    assert isinstance(cache_dir, Path)
    assert cache_dir.exists()
    assert cache_dir.is_dir()


def test_regression_cache_dir():
    """Test regression cache directory creation."""
    cache_dir = get_cache_dir(use_regression=True)
    assert isinstance(cache_dir, Path)
    assert cache_dir.exists()
    assert cache_dir.is_dir()
    assert "regression" in str(cache_dir)


def test_cache_dir_separation():
    """Test that normal and regression caches are separate."""
    normal_cache = get_cache_dir(use_regression=False)
    regression_cache = get_cache_dir(use_regression=True)
    assert normal_cache != regression_cache

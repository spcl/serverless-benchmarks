# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""
Module for handling benchmarks in the Serverless Benchmarking Suite (SeBS).

This module provides classes for benchmark configuration, code packaging, and execution.
It handles the preparation of code packages with dependencies for deployment to
various serverless platforms, including caching mechanisms to avoid redundant builds.
"""
from __future__ import annotations

import glob
import hashlib
import json
import subprocess
import os
import shutil
import textwrap
from abc import abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

import docker

from sebs.cpp_dependencies import CppDependencies

from sebs.config import SeBSConfig
from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.container import DockerContainer
from sebs.faas.resources import SystemResources
from sebs.faas.storage import PersistentStorage
from sebs.utils import find_benchmark, get_resource_path, ensure_benchmarks_data, LoggingBase
from sebs.sebs_types import BenchmarkModule, Language
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebs.experiments.config import Config as ExperimentConfig


class LanguageSpec:
    """
    Represents a language with its supported variants for a benchmark.

    Parses the config language settings, supports both the legacy format
    (e.g. "python") and the new dict format:

    {"language": "nodejs", "variants": ["default", "bun", "llrt"]}

    The legacy format is treated as having just the "default" variant.
    """

    def __init__(self, language: "Language", variants: List[str]):
        """Initialize a language specification.

        Args:
            language: The programming language
            variants: List of supported runtime variants for this language
        """
        self._language = language
        self._variants = variants

    @property
    def language(self) -> "Language":
        """Get the programming language.

        Returns:
            Language: The programming language
        """
        return self._language

    @property
    def variants(self) -> List[str]:
        """Get the list of supported runtime variants.

        Returns:
            List[str]: List of variant names (e.g., ["default", "pypy"])
        """
        return self._variants

    @staticmethod
    def deserialize(val) -> LanguageSpec:
        """Deserialize a language specification from config.

        Args:
            val: Either a string (legacy format) or dict with language and variants

        Returns:
            LanguageSpec: Deserialized language specification
        """
        if isinstance(val, str):
            return LanguageSpec(Language.deserialize(val), ["default"])
        return LanguageSpec(
            Language.deserialize(val["language"]),
            val.get("variants", ["default"]),
        )

    def serialize(self) -> dict:
        """Serialize the language specification to a dictionary.

        Returns:
            dict: Dictionary with language and variants keys
        """
        return {
            "language": self._language.value,
            "variants": self._variants,
        }


class BenchmarkConfig:
    """
    Configuration for a benchmark in the Serverless Benchmarking Suite.

    This class stores the configuration parameters for a benchmark, including
    timeout, memory allocation, supported languages, and included modules.

    Attributes:

        timeout: Maximum execution time in seconds
        memory: Memory allocation in MB
        languages: List of supported programming languages
        modules: List of benchmark modules/features required

    """

    def __init__(
        self,
        timeout: int,
        memory: int,
        language_specs: List["LanguageSpec"],
        modules: List[BenchmarkModule],
        cpp_dependencies: Optional[List[CppDependencies]] = None,
    ):
        """
        Initialize a benchmark configuration.

        Args:
            timeout: Maximum execution time in seconds
            memory: Memory allocation in MB
            languages: List of supported programming languages
            modules: List of benchmark modules/features required
        """
        self._timeout = timeout
        self._memory = memory
        self._language_specs = language_specs
        self._modules = modules
        self._cpp_dependencies = cpp_dependencies or []

    @property
    def timeout(self) -> int:
        """
        Get the maximum execution time in seconds.

        Returns:
            int: The timeout value
        """
        return self._timeout

    @timeout.setter
    def timeout(self, val: int):
        """
        Set the maximum execution time in seconds.

        Args:
            val: The new timeout value
        """
        self._timeout = val

    @property
    def memory(self) -> int:
        """
        Get the memory allocation in MB.

        Returns:
            int: The memory allocation
        """
        return self._memory

    @memory.setter
    def memory(self, val: int):
        """
        Set the memory allocation in MB.

        Args:
            val: The new memory allocation value
        """
        self._memory = val

    @property
    def language_specs(self) -> List[LanguageSpec]:
        """Get the list of language specifications with their variants.

        Returns:
            List[LanguageSpec]: Language specifications for this benchmark
        """
        return self._language_specs

    @property
    def languages(self) -> List[Language]:
        """
        Get the list of supported programming languages.

        Returns:
            List[Language]: Supported programming languages
        """
        return [spec.language for spec in self._language_specs]

    @property
    def modules(self) -> List[BenchmarkModule]:
        """
        Get the list of benchmark modules/features required.

        Returns:
            List[BenchmarkModule]: Required benchmark modules
        """
        return self._modules

    def supported_variants(self, language: Language) -> List[str]:
        """Return the list of variants supported for the given language,
        or [] if the language has no implementation in this benchmark."""
        for spec in self._language_specs:
            if spec.language == language:
                return spec.variants
        return []

    def supports(self, language: Language, variant: str) -> bool:
        """Return True when language + variant combination is declared in config.json."""
        return variant in self.supported_variants(language)

    @staticmethod
    def deserialize(json_object: dict) -> BenchmarkConfig:
        """
        Create a BenchmarkConfig instance from a JSON object.

        Args:
            json_object: Dictionary containing benchmark configuration

        Returns:
            BenchmarkConfig: A new instance with the deserialized data
        """
        return BenchmarkConfig(
            json_object["timeout"],
            json_object["memory"],
            [LanguageSpec.deserialize(x) for x in json_object["languages"]],
            [BenchmarkModule(x) for x in json_object["modules"]],
            cpp_dependencies=[
                CppDependencies.deserialize(x) for x in json_object.get("cpp_dependencies", [])
            ],
        )


class Benchmark(LoggingBase):
    """
    Creates code package representing a benchmark with all code and assets.

    This class handles building, packaging, and deploying benchmark code for
    serverless platforms.
    This includes copying source files, adding deployment-specific wrappers,
    adding deployment-specific dependencies, and installing application dependencies
    within Docker images corresponding to the target cloud deployment.
    Code packages are cached.

    The behavior of this class, particularly the `build` method, depends on the
    state of the SeBS cache:

    1. If no cache entry exists for the benchmark (for the current language, deployment, etc.),
       a new code package is built.
    2. If a cache entry exists, the hash of the benchmark's source directory is computed
       and compared with the hash of cached package. If they differ, or if an update is forced,
       the package is rebuilt.
    3. Otherwise (cache entry exists and hash matches), the cached code package is used.

    Attributes:
        benchmark: Name of the benchmark
        benchmark_path: Path to the benchmark directory
        benchmark_config: Configuration for the benchmark
        code_package: Dictionary with code package information
        functions: Dictionary of functions for this benchmark
        code_location: Location of the code package
        is_cached: Whether the benchmark is cached
        is_cached_valid: Whether the cached benchmark is valid
        code_size: Size of the code package in bytes
        container_uri: URI of the container for container deployments
        language: Programming language for the benchmark
        language_name: Name of the programming language
        language_version: Version of the programming language
        has_input_processed: Whether input processing has been performed
        uses_storage: Whether the benchmark uses cloud storage
        uses_nosql: Whether the benchmark uses NoSQL databases
        architecture: CPU architecture of the deployment target
        container_deployment: Whether using container deployment

    """

    _hash_value: Optional[str]

    @staticmethod
    def typename() -> str:
        """
        Get the type name of this class.

        Returns:
            str: The type name
        """
        return "Benchmark"

    @property
    def benchmark(self) -> str:
        """
        Get the benchmark name.

        Returns:
            str: Name of the benchmark
        """
        return self._benchmark

    @property
    def benchmark_path(self) -> str:
        """
        Get the path to the benchmark directory.

        Returns:
            str: Path to the benchmark directory
        """
        assert self._benchmark_path is not None
        return self._benchmark_path

    @property
    def benchmark_config(self) -> BenchmarkConfig:
        """
        Get the benchmark configuration.

        Returns:
            BenchmarkConfig: Configuration for the benchmark
        """
        return self._benchmark_config

    @property
    def code_package(self) -> Dict[str, Any]:
        """
        Get the cached code package information, if available.
        This typically includes 'location' (relative to cache_dir), 'hash', and 'size'.

        Returns:
            Dict[str, Any]: Dictionary with code package information
        """
        assert self._code_package is not None
        return self._code_package

    @property
    def functions(self) -> Dict[str, Any]:
        """
        Get the cached information about deployed functions associated
        with this benchmark for the current deployment, keyed by function name.

        Returns:
            Dict[str, Any]: Dictionary of functions
        """
        assert self._functions is not None
        return self._functions

    @property
    def code_location(self) -> str | None:
        """
        Get the absolute path to the prepared code package.
        If cached, it points to the location within the SeBS cache directory.
        Otherwise, it points to the build output directory.

        Returns:
            str: Path to the code package
        """
        if self._code_package:
            if "location" in self.code_package:
                """
                Access cached code package instead of a built one.
                """
                return os.path.join(self._cache_client.cache_dir, self.code_package["location"])
            return None
        else:
            return self._code_location

    @property
    def is_cached(self) -> bool:
        """
        Check if the benchmark is cached.

        Returns:
            bool: True if cached, False otherwise
        """
        return self._is_cached

    @is_cached.setter
    def is_cached(self, val: bool):
        """
        Set whether the benchmark is cached.

        Args:
            val: True if cached, False otherwise
        """
        self._is_cached = val

    @property
    def is_cached_valid(self) -> bool:
        """
        True if a cached code package exists and its hash matches the current
        benchmark source code hash.

        Returns:
            bool: True if valid, False otherwise
        """
        return self._is_cached_valid

    @is_cached_valid.setter
    def is_cached_valid(self, val: bool):
        """
        Set whether the cached benchmark is valid.

        Args:
            val: True if valid, False otherwise
        """
        self._is_cached_valid = val

    @property
    def code_size(self) -> int:
        """
        Get the size of the code package in bytes.

        Returns:
            int: Size in bytes
        """
        return self._code_size

    @property
    def container_uri(self) -> str:
        """
        Get the URI of the container for container deployments.

        Returns:
            str: Container URI

        Raises:
            AssertionError: If container URI is None
        """
        assert self._container_uri is not None
        return self._container_uri

    @property
    def language(self) -> "Language":
        """
        Get the programming language for the benchmark.

        Returns:
            Language: Programming language
        """
        return self._language

    @property
    def language_name(self) -> str:
        """
        Get the name of the programming language, e.g., "python".

        Returns:
            str: Name of the language
        """
        return self._language.value

    @property
    def language_variant(self) -> str:
        """Get the language runtime variant.

        Returns:
            str: The runtime variant (e.g., "default", "pypy", "bun")
        """
        return self._language_variant

    @property
    def cache_language_key(self) -> str:
        """
        Add language variant to the cache key so that different variants of
        the same language don't conflict in cache.
        """
        base_key = self._language.value
        if self._language_variant != "default":
            base_key = f"{base_key}_{self._language_variant}"
        if self._system_variant_suffix:
            return f"{base_key}_{self._system_variant_suffix}"
        return base_key

    @property
    def language_version(self) -> str:
        """
        Get the version of the programming language, e.g. "3.8".

        Returns:
            str: Version of the language
        """
        return self._language_version

    @property
    def has_input_processed(self) -> bool:
        """
        Check if input processing has been performed.

        Returns:
            bool: True if processed, False otherwise
        """
        return self._input_processed

    @property
    def uses_storage(self) -> bool:
        """
        Check if the benchmark uses cloud storage.

        Returns:
            bool: True if using storage, False otherwise
        """
        return self._uses_storage

    @property
    def uses_nosql(self) -> bool:
        """
        Check if the benchmark uses NoSQL databases.

        Returns:
            bool: True if using NoSQL, False otherwise
        """
        return self._uses_nosql

    @property
    def architecture(self) -> str:
        """
        Get the CPU architecture of the deployment target.

        Returns:
            str: Architecture name (e.g., 'x86_64', 'arm64')
        """
        return self._architecture

    @property
    def container_deployment(self) -> bool:
        """
        Check if using container deployment.

        Returns:
            bool: True if using container deployment, False otherwise
        """
        return self._container_deployment

    @property  # noqa: A003
    def hash(self) -> str:
        """
        Get the hash of the benchmark code.

        Computes an MD5 hash of the benchmark directory to determine if
        the code has changed since the last build.

        Returns:
            str: MD5 hash as a hexadecimal string
        """
        path = os.path.join(self.benchmark_path, self.language_name)
        self._hash_value = Benchmark.hash_directory(
            path, self._deployment_name, self.language, self._language_variant
        )
        return self._hash_value

    @hash.setter  # noqa: A003
    def hash(self, val: str):
        """
        Set the hash of the benchmark code.

        Used only for testing purposes.

        Args:
            val: MD5 hash as a hexadecimal string
        """
        self._hash_value = val

    def __init__(
        self,
        benchmark: str,
        deployment_name: str,
        config: "ExperimentConfig",
        system_config: SeBSConfig,
        output_dir: str,
        cache_client: Cache,
        docker_client: docker.client.DockerClient,
        system_variant_suffix: Optional[str] = None,
        verbose: bool = False,
    ):
        """
        Initialize a Benchmark instance.

        Sets up a benchmark for a specific deployment platform, including configuration,
        language runtime, and caching. Loads the benchmark configuration from the JSON file
        and validates the language support.

        Args:
            benchmark: Name of the benchmark
            deployment_name: Name of the deployment platform (e.g., 'aws', 'azure')
            config: Experiment configuration
            system_config: SeBs system configuration
            output_dir: Directory for output files
            cache_client: Cache client for caching code packages
            docker_client: Docker client for building dependencies
            system_variant_suffix: Optional provider-local system variant suffix
            verbose: Print verbose build logs.

        Raises:
            RuntimeError: If the benchmark is not found or doesn't support the language
        """
        super().__init__()
        self._benchmark = benchmark
        self._deployment_name = deployment_name
        self._experiment_config = config
        self._language = config.runtime.language
        self._language_version = config.runtime.version
        assert config.runtime.variant is not None
        self._language_variant = config.runtime.variant.value
        self._architecture = self._experiment_config.architecture
        self._container_deployment = config.container_deployment
        self._system_variant_suffix = system_variant_suffix
        self._verbose = verbose

        benchmark_path = find_benchmark(self.benchmark, "benchmarks")
        if not benchmark_path:
            raise RuntimeError("Benchmark {benchmark} not found!".format(benchmark=self._benchmark))
        self._benchmark_path = benchmark_path

        with open(os.path.join(self.benchmark_path, "config.json")) as json_file:
            self._benchmark_config: BenchmarkConfig = BenchmarkConfig.deserialize(
                json.load(json_file)
            )
        if not self.benchmark_config.supports(self.language, self._language_variant):
            raise RuntimeError(
                "Benchmark {} not available for language {} variant {}".format(
                    self.benchmark, self.language, self._language_variant
                )
            )
        self._cache_client = cache_client
        self._docker_client = docker_client
        self._system_config = system_config
        self._code_location: Optional[str] = None
        self._output_dir = os.path.join(
            output_dir,
            f"{benchmark}_code",
            self._language.value,
            self._language_variant,
            self._language_version,
            self._architecture,
            (
                "container"
                if self._container_deployment
                else (
                    f"package_{self._system_variant_suffix}"
                    if self._system_variant_suffix
                    else "package"
                )
            ),
        )
        self._container_uri: Optional[str] = None

        # verify existence of function in cache
        self.query_cache()
        if config.update_code:
            self._is_cached_valid = False

        # Try to ensure benchmarks-data exists
        ensure_benchmarks_data(self.logging)

        # Load input module
        self._benchmark_data_path = find_benchmark(self._benchmark, "benchmarks-data")
        self._benchmark_input_module = load_benchmark_input(self._benchmark_path)

        # Check if input has been processed
        self._input_processed: bool = False
        self._uses_storage: bool = False
        self._uses_nosql: bool = False

    @staticmethod
    def hash_directory(
        directory: str, deployment: str, language: Language, variant: str = "default"
    ):
        """
        Compute MD5 hash of an entire directory.

        Calculates a hash of the benchmark source code by combining hashes of all
        relevant files. This includes language-specific files, deployment wrappers,
        and shared files like shell scripts and JSON configuration.

        Args:
            directory: Path to the directory to hash
            deployment: Name of the deployment platform
            language: Programming language name

        Returns:
            str: MD5 hash as a hexadecimal string
        """
        hash_sum = hashlib.md5()
        FILES = {
            Language.PYTHON: ["*.py", "requirements.txt*"],
            Language.NODEJS: ["*.js", "package.json"],
            Language.JAVA: ["*.java", "pom.xml"],
            Language.CPP: ["*.cpp", "*.hpp", "dependencies.json"],
        }
        WRAPPERS = {
            Language.PYTHON: ["*.py"],
            Language.NODEJS: ["*.js"],
            Language.JAVA: ["src"],
            Language.CPP: ["*.cpp", "*.hpp"],
        }
        NON_LANG_FILES = ["*.sh", "*.json"]
        selected_files = FILES[language] + NON_LANG_FILES
        for file_type in selected_files:
            for f in glob.glob(os.path.join(directory, file_type)):
                path = os.path.join(directory, f)
                with open(path, "rb") as opened_file:
                    hash_sum.update(opened_file.read())
        # Include variant overlay files (or patch) in the hash so that a
        # change to the variant directory invalidates the cached package.
        if variant != "default":
            variant_dir = os.path.join(directory, variant)
            if os.path.isdir(variant_dir):
                patch_file = os.path.join(variant_dir, "patch.diff")
                if os.path.exists(patch_file):
                    with open(patch_file, "rb") as pf:
                        hash_sum.update(pf.read())
                else:
                    for file_type in selected_files:
                        for f in glob.glob(os.path.join(variant_dir, file_type)):
                            with open(f, "rb") as opened_file:
                                hash_sum.update(opened_file.read())
        # wrappers
        wrapper_patterns = WRAPPERS[language]
        for pattern in wrapper_patterns:
            wrappers = get_resource_path(
                "benchmarks", "wrappers", deployment, language.value, pattern
            )
            for f in glob.glob(str(wrappers)):
                if os.path.isdir(f):
                    for root, _, files in os.walk(f):
                        for file in files:
                            path = os.path.join(root, file)
                            with open(path, "rb") as opened_file:
                                hash_sum.update(opened_file.read())
                else:
                    with open(f, "rb") as opened_file:
                        hash_sum.update(opened_file.read())
        return hash_sum.hexdigest()

    def serialize(self) -> dict:
        """
        Serialize the benchmark to a dictionary.

        Returns:
            dict: Dictionary containing size and hash of the benchmark code
        """
        return {"size": self.code_size, "hash": self.hash}

    def query_cache(self) -> None:
        """
        Query the cache for existing benchmark code packages and functions.

        Checks if there's a cached code package or container for this benchmark
        and deployment combination. Updates the cache status fields based on
        whether the cache exists and if it's still valid (hash matches).
        """
        if self.container_deployment:
            self._code_package = self._cache_client.get_container(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.cache_language_key,
                language_version=self.language_version,
                architecture=self.architecture,
            )
            if self._code_package is not None:
                self._container_uri = self._code_package["image-uri"]
        else:
            self._code_package = self._cache_client.get_code_package(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.cache_language_key,
                language_version=self.language_version,
                architecture=self.architecture,
            )

        self._functions = self._cache_client.get_functions(
            deployment=self._deployment_name,
            benchmark=self._benchmark,
            language=self.cache_language_key,
        )

        if self._code_package is not None:
            # compare hashes
            current_hash = self.hash
            old_hash = self._code_package["hash"]
            self._code_size = self._code_package["size"]
            self._is_cached = True
            self._is_cached_valid = current_hash == old_hash
        else:
            self._is_cached = False
            self._is_cached_valid = False

    def copy_code(self, output_dir: str) -> None:
        """Copy benchmark source code to output directory.

        Copies language-specific source files and dependency files from the
        benchmark directory to the output directory for deployment preparation.
        Handles Python requirements files, Node.js package.json files, and Java projects.

        Args:
            output_dir: Destination directory for copied files
        """
        FILES = {
            Language.PYTHON: ["*.py", "requirements.txt*"],
            Language.NODEJS: ["*.js", "package.json"],
            Language.JAVA: [],
            Language.CPP: ["*.cpp", "*.hpp", "dependencies.json"],
        }
        path = os.path.join(self.benchmark_path, self.language_name)
        if self.language == Language.JAVA:
            # In Java, we copy the entire nested directory.
            shutil.copytree(path, output_dir, dirs_exist_ok=True)
            return
        for file_type in FILES[self.language]:
            for f in glob.glob(os.path.join(path, file_type)):
                shutil.copy2(os.path.join(path, f), output_dir)

        # support node.js benchmarks with language specific packages
        nodejs_package_json = os.path.join(path, f"package.json.{self.language_version}")
        if os.path.exists(nodejs_package_json):
            shutil.copy2(nodejs_package_json, os.path.join(output_dir, "package.json"))

        if self._language_variant != "default":
            variant_dir = os.path.join(path, self._language_variant)
            if not os.path.isdir(variant_dir):
                raise RuntimeError(
                    "Variant directory not found for benchmark {} language {} "
                    "variant {}: {}".format(
                        self.benchmark, self.language_name, self._language_variant, variant_dir
                    )
                )

            patch_file = os.path.join(variant_dir, "patch.diff")
            if os.path.exists(patch_file):
                # Patch-based variant: a unified diff (patch.diff) is applied on top of the
                # default implementation.  Use this when the variant only needs small
                # targeted changes to the base code (e.g. swapping async I/O for sync I/O
                # in a runtime that lacks full async support).
                # Apply unified diff on top of the already-copied base files
                import patch_ng

                pset = patch_ng.fromfile(patch_file)
                if not pset or not pset.apply(strip=1, root=output_dir):
                    raise RuntimeError(
                        "Failed to apply patch {} for variant {}".format(
                            patch_file, self._language_variant
                        )
                    )
                self.logging.info(
                    "Applied patch for variant {} ({})".format(self._language_variant, patch_file)
                )
            else:
                # Overlay-based variant: the variant directory contains a complete
                # replacement set of source files that fully override the default
                # implementation.  All files from the variant directory are copied
                # on top of the already-placed base files.  Use this when the variant
                # is substantially different from the default (e.g. a full rewrite).
                for file_type in FILES[self.language]:
                    for f in glob.glob(os.path.join(variant_dir, file_type)):
                        shutil.copy2(f, output_dir)
                # version-specific package.json override for Node.js
                nodejs_variant_pkg = os.path.join(
                    variant_dir, f"package.json.{self.language_version}"
                )
                if os.path.exists(nodejs_variant_pkg):
                    shutil.copy2(nodejs_variant_pkg, os.path.join(output_dir, "package.json"))
                self.logging.info(
                    "Applied file overlay for variant {}".format(self._language_variant)
                )

    def add_benchmark_data(self, output_dir: str) -> None:
        """Add benchmark-specific data and assets to output directory.

        Executes benchmark initialization scripts (init.sh) if present in
        the benchmark directory. These scripts typically download or generate
        additional data files required by the benchmark.

        Args:
            output_dir: Directory where benchmark data should be added
        """
        cmd = "/bin/bash '{benchmark_path}/init.sh' '{output_dir}' false {architecture}"
        paths = [
            self.benchmark_path,
            os.path.join(self.benchmark_path, self.language_name),
        ]
        for path in paths:
            if os.path.exists(os.path.join(path, "init.sh")):
                full_cmd = cmd.format(
                    benchmark_path=path,
                    output_dir=output_dir,
                    architecture=self._experiment_config._architecture,
                )
                self.logging.debug("Adding benchmark data with command: {}".format(full_cmd))
                result = subprocess.run(
                    full_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                output = result.stdout.decode("utf-8", errors="replace").strip()
                if output:
                    self.logging.debug("init.sh output:\n{}".format(output))
                if result.returncode != 0:
                    raise RuntimeError(
                        "init.sh failed (exit {}): {}".format(result.returncode, output)
                    )

    def add_deployment_files(self, output_dir: str) -> None:
        """Add deployment-specific wrapper files to output directory.

        Copies platform-specific wrapper files (handlers, adapters) that
        integrate the benchmark code with the target FaaS platform's
        execution environment.

        Files are sourced from `benchmarks/wrappers/{deployment_name}/{language_name}/`.

        Args:
            output_dir: Directory where deployment files should be added
        """
        handlers_dir = get_resource_path(
            "benchmarks", "wrappers", self._deployment_name, self.language_name
        )
        handlers = [
            os.path.join(handlers_dir, file)
            for file in self._system_config.deployment_files(
                self._deployment_name, self.language_name
            )
        ]

        for file in handlers:
            destination = os.path.join(output_dir, os.path.basename(file))
            if os.path.isdir(file):
                shutil.copytree(file, destination, dirs_exist_ok=True)
            else:
                if not os.path.exists(destination):
                    shutil.copy2(file, destination)

    def add_deployment_package_python(self, output_dir: str) -> None:
        """Add Python deployment packages to requirements file.

        Appends platform-specific Python packages and benchmark module
        dependencies to the requirements.txt file for the deployment.

        Handles versioned requirements files (e.g., requirements.txt.3.8).

        Args:
            output_dir: Directory containing the requirements file to modify
        """

        destination_file = f"requirements.txt.{self._language_version}"
        if not os.path.exists(os.path.join(output_dir, destination_file)):
            destination_file = "requirements.txt"

        # append to the end of requirements file
        with open(os.path.join(output_dir, destination_file), "a") as out:
            packages = self._system_config.deployment_packages(
                self._deployment_name, self.language_name
            )
            for package in packages:
                out.write(package)

            module_packages = self._system_config.deployment_module_packages(
                self._deployment_name, self.language_name
            )
            for bench_module in self._benchmark_config.modules:
                if bench_module.value in module_packages:
                    for package in module_packages[bench_module.value]:
                        out.write(package)

    def add_deployment_package_nodejs(self, output_dir: str) -> None:
        """Add Node.js deployment packages to package.json.

        Modifies the package.json file to include platform-specific
        Node.js dependencies required for deployment.
        Handles versioned package.json files (e.g., package.json.12).

        Args:
            output_dir: Directory containing the package.json file to modify
        """
        # modify package.json
        packages = self._system_config.deployment_packages(
            self._deployment_name, self.language_name
        )
        if len(packages):
            package_config = os.path.join(output_dir, f"package.json.{self._language_version}")
            if not os.path.exists(package_config):
                package_config = os.path.join(output_dir, "package.json")

            with open(package_config, "r") as package_file:
                package_json = json.load(package_file)
            for key, val in packages.items():
                package_json["dependencies"][key] = val
            with open(package_config, "w") as package_file:
                json.dump(package_json, package_file, indent=2)

    def format_maven_dependency(self, group_artifact: str, version: str) -> str:
        """Helper method to format Java system dependencies.
        Dependencies in system.json are in "group:artifact": version format;
        this function converts them to proper Maven <dependency> blocks.

        Args:
            group_artifact: name of library to add to benchmark
            version: library version

        Returns:
            XML-formatted block inserted into pom.xml
        """
        group_id, artifact_id = group_artifact.split(":")
        return f"""
        <dependency>
            <groupId>{group_id}</groupId>
            <artifactId>{artifact_id}</artifactId>
            <version>{version}</version>
        </dependency>"""

    def add_deployment_package_java(self, output_dir: str):
        """Extend benchmark's pom.xml with system-specific packages.
        All Java dependencies for each platform are defined in systems.json.

        Args:
            output_dir: benchmark directory containing pom.xml to modify

        Raises:
            ValueError: when benchmark's pom.xml is missing placeholder
        """
        pom_path = os.path.join(output_dir, "pom.xml")
        with open(pom_path, "r") as f:
            pom_content = f.read()

        packages = self._system_config.deployment_packages(
            self._deployment_name, self.language_name
        )

        dependency_blocks = ""
        if len(packages):
            for key, val in packages.items():
                dependency_name = key.strip('"').strip("'")
                dependency_version = val.strip('"').strip("'")
                dependency_blocks += (
                    self.format_maven_dependency(dependency_name, dependency_version) + "\n"
                )

        if "<!-- PLATFORM_DEPENDENCIES -->" not in pom_content:
            raise ValueError(
                "pom.xml template is missing <!-- PLATFORM_DEPENDENCIES --> placeholder"
            )

        pom_content = pom_content.replace(
            "<!-- PLATFORM_DEPENDENCIES -->", dependency_blocks.strip()
        )

        with open(pom_path, "w") as f:
            f.write(pom_content)

    def add_deployment_package_cpp(self, output_dir: str) -> None:
        """Generates CMakeLists.txt file for C++ benchmark.

        The CMake file contains multiple steps:
        * Basic definition of benchmark target.
        * Packaging instructions for AWS.
        * Linking dependencies required by the benchmark.
        * Linking AWS SDK and Hiredis.

        Args:
            output_dir: Benchmark directory
        """

        files = ["handler.cpp", "utils.cpp", "main.cpp"]
        if BenchmarkModule.STORAGE in self.benchmark_config.modules:
            files.append("storage.cpp")
        if BenchmarkModule.NOSQL in self.benchmark_config.modules:
            files.append("key-value.cpp")
        # TODO: add module for redis
        files_str = " ".join(files)

        cmake_script = f"""
        cmake_minimum_required(VERSION 3.9)
        set(CMAKE_CXX_STANDARD 14)
        # set(CMAKE_CXX_FLAGS "-Os")
        project(benchmark LANGUAGES CXX)
        set(CMAKE_CXX_STANDARD 17)
        add_executable(
            ${{PROJECT_NAME}} {files_str}
        )
        target_include_directories(${{PROJECT_NAME}} PRIVATE ".")

        target_compile_features(${{PROJECT_NAME}} PRIVATE "cxx_std_14")
        target_compile_options(${{PROJECT_NAME}} PRIVATE "-Wall" "-Wextra")

        find_package(aws-lambda-runtime)
        target_link_libraries(${{PROJECT_NAME}} PRIVATE AWS::aws-lambda-runtime)
        """

        for dependency in self._benchmark_config._cpp_dependencies:
            cmake_script += CppDependencies.to_cmake_list(dependency)

        """
            FIXME: we disabled Hiredis as this is currently not used.
            We need a proper module for that.
        """

        cmake_script += """

        # find_package(PkgConfig REQUIRED)
        # set(ENV{PKG_CONFIG_PATH} "/opt/lib/pkgconfig")
        # pkg_check_modules(HIREDIS REQUIRED IMPORTED_TARGET hiredis)

        # target_include_directories(${PROJECT_NAME} PUBLIC PkgConfig::HIREDIS)
        # target_link_libraries(${PROJECT_NAME} PUBLIC PkgConfig::HIREDIS)

        # this line creates a target that packages your binary and zips it up
        aws_lambda_package_target(${PROJECT_NAME})
        """

        self.logging.info(
            f"CPP benchmark {self.benchmark} has "
            + str(len(self._benchmark_config._cpp_dependencies))
            + " dependencies."
        )

        build_script = os.path.join(output_dir, "CMakeLists.txt")
        with open(build_script, "w") as script_file:
            script_file.write(textwrap.dedent(cmake_script))

    def add_deployment_package(self, output_dir: str) -> None:
        """Add deployment packages based on programming language.

        Delegates to language-specific package addition methods to include
        platform-specific dependencies in the deployment package.

        Args:
            output_dir: Directory where deployment packages should be added

        Raises:
            NotImplementedError: If the language is not supported
        """

        if self.language == Language.PYTHON:
            self.add_deployment_package_python(output_dir)
        elif self.language == Language.NODEJS:
            self.add_deployment_package_nodejs(output_dir)
        elif self.language == Language.JAVA:
            self.add_deployment_package_java(output_dir)
        elif self.language == Language.CPP:
            self.add_deployment_package_cpp(output_dir)
        else:
            raise NotImplementedError

    @staticmethod
    def directory_size(directory: str) -> int:
        """Calculate total size of all files in a directory.

        Recursively calculates the total size in bytes of all files
        within the specified directory and its subdirectories.

        Args:
            directory: Path to the directory to measure

        Returns:
            int: Total size in bytes of all files in the directory
        """
        from pathlib import Path

        root = Path(directory)
        sizes = [f.stat().st_size for f in root.glob("**/*") if f.is_file()]
        return sum(sizes)

    def builder_image_name(self) -> Tuple[str, str]:
        """Image names of builder Docker images for preparing benchmarks.

        Returns two image names for fallback behavior:
        - Current version image (tagged with current SeBS version)
        - Previous version image (tagged with previous major SeBS version)

        This allows new SeBS versions to use images from the previous stable
        version without requiring a complete rebuild of all images.

        Returns:
            Tuple of (previous_version_image_name, current_version_image_name).
        """
        base_image_name = "build.{deployment}.{language}.{runtime}".format(
            deployment=self._deployment_name,
            language=self.language_name,
            runtime=self.language_version,
        )
        # Current version image (try this first)
        current_version_image_name = "{base}-{version}".format(
            base=base_image_name,
            version=self._system_config.version(),
        )
        # Previous major version image (fallback)
        previous_version_image_name = "{base}-{version}".format(
            base=base_image_name,
            version=self._system_config.previous_version(),
        )

        return previous_version_image_name, current_version_image_name

    def install_dependencies(self, output_dir: str) -> None:
        """Install benchmark dependencies using Docker.

        Uses Docker containers to install language-specific dependencies
        (pip packages for Python, npm packages for Node.js) in an environment
        matching the target deployment platform.
        Pulls a pre-built Docker image specific to the deployment, language, and
        runtime version. Mounts the output directory into the container and runs
        an installer script (`/sebs/installer.sh`) within the container.

        Tries current SeBS version image first, falls back to previous major version
        image if the current version image is not available. This allows new SeBS
        versions to use images from the previous stable version without requiring
        a complete rebuild.

        Args:
            output_dir: Directory containing the code package to build

        Raises:
            RuntimeError: If Docker image pull fails
            docker.errors.ContainerError: If dependency installation fails
        """
        # do we have docker image for this run and language?
        if "build" not in self._system_config.docker_image_types(
            self._deployment_name, self.language_name
        ):
            self.logging.info(
                (
                    "There is no Docker build image for {deployment} run in {language}, "
                    "thus skipping the Docker-based installation of dependencies."
                ).format(deployment=self._deployment_name, language=self.language_name)
            )
        else:
            repo_name = self._system_config.docker_repository()
            previous_version_image_name, current_version_image_name = self.builder_image_name()

            def ensure_image(name: str) -> None:
                """Internal implementation of checking for Docker image existence.

                Args:
                    name: image name

                Raises:
                    RuntimeError: when image does not exist locally or cannot be pulled.
                """
                try:
                    self._docker_client.images.get(repo_name + ":" + name)
                except docker.errors.ImageNotFound:
                    try:
                        self.logging.info(
                            "Docker pull of image {repo}:{image}".format(repo=repo_name, image=name)
                        )
                        self._docker_client.images.pull(repo_name, name)
                    except docker.errors.APIError:
                        raise RuntimeError(
                            "Docker pull of image {}:{} failed!".format(repo_name, name)
                        )

            # Try current version image first, fallback to previous version if not available
            image_name = current_version_image_name
            try:
                ensure_image(current_version_image_name)
            except RuntimeError as e:
                self.logging.warning(
                    "Failed to ensure image {}, falling back to {}: {}".format(
                        current_version_image_name, previous_version_image_name, e
                    )
                )
                try:
                    ensure_image(previous_version_image_name)
                    # update `image_name` to the fallback image name
                    image_name = previous_version_image_name
                except RuntimeError:
                    raise

            # Create set of mounted volumes
            volumes = {os.path.abspath(output_dir): {"bind": "/mnt/function", "mode": "rw"}}
            package_script = os.path.abspath(
                os.path.join(self._benchmark_path, self.language_name, "package.sh")
            )
            # does this benchmark has package.sh script?
            if os.path.exists(package_script):
                volumes[package_script] = {
                    "bind": "/mnt/function/package.sh",
                    "mode": "ro",
                }

            # run Docker container to install packages
            PACKAGE_FILES = {
                Language.PYTHON: "requirements.txt",
                Language.NODEJS: "package.json",
                Language.CPP: "CMakeLists.txt",
                Language.JAVA: "pom.xml",
            }
            file = os.path.join(output_dir, PACKAGE_FILES[self.language])
            if os.path.exists(file):
                try:
                    self.logging.info(
                        "Docker build of benchmark dependencies in container "
                        "of image {repo}:{image}".format(repo=repo_name, image=image_name)
                    )
                    self.logging.info(
                        "Docker mount of benchmark code from path {path}".format(
                            path=os.path.abspath(output_dir)
                        )
                    )
                    container = self._docker_client.containers.run(
                        "{}:{}".format(repo_name, image_name),
                        volumes=volumes,
                        environment={
                            "CONTAINER_UID": str(os.getuid()),
                            "CONTAINER_GID": str(os.getgid()),
                            "CONTAINER_USER": "docker_user",
                            "APP": self.benchmark,
                            "PLATFORM": self._deployment_name.upper(),
                            "TARGET_ARCHITECTURE": self._experiment_config._architecture,
                        },
                        remove=False,
                        detach=True,
                    )
                    try:
                        exit_code = container.wait()
                        stdout = container.logs()

                        error_log_path: str = ""
                        if exit_code["StatusCode"] != 0:
                            error_log_path = os.path.join(output_dir, "error.log")
                        elif self._verbose:
                            error_log_path = os.path.join(output_dir, "build.log")

                        if exit_code["StatusCode"] != 0 or self._verbose:
                            with open(error_log_path, "wb") as error_file:
                                error_file.write(stdout)

                        if exit_code["StatusCode"] != 0:
                            self.logging.error(
                                f"Build failed! Container exited with "
                                f"code {exit_code['StatusCode']}"
                            )
                            self.logging.error(f"Logs saved to {error_log_path}")
                            raise RuntimeError("Package build failed!")

                        self.logging.debug(f"Build Build logs saved to {error_log_path}")
                    finally:
                        container.remove()

                    # Pass to output information on optimizing builds.
                    # Useful for AWS where packages have to obey size limits.
                    for line in stdout.decode("utf-8").split("\n"):
                        if "size" in line:
                            self.logging.info("Docker build: {}".format(line))
                except docker.errors.ContainerError as e:
                    self.logging.error("Package build failed!")
                    self.logging.error(f"Stderr: {e.stderr}")
                    self.logging.error(f"Docker mount volumes: {volumes}")
                    raise e from None

    def recalculate_code_size(self) -> int:
        """Recalculate and update the code package size.

        Measures the current size of the output directory and updates
        the internal code size tracking.

        Returns:
            int: Updated code package size in bytes
        """
        self._code_size = Benchmark.directory_size(self._output_dir)
        return self._code_size

    def build(
        self,
        package_build_step: Callable[[str, Language, str, str, str, bool], Tuple[str, int]],
        container_client: DockerContainer | None,
        container_build_step: Callable[[str, Language, str, str, str, bool], Tuple[str, int]]
        | None,
    ) -> Tuple[bool, str | None, bool, str | None]:
        """Build the complete benchmark deployment package.

        Orchestrates the entire build process for a benchmark, including:
        - Code copying and dependency installation
        - Adding benchmark data and deployment-specific files
        - Running platform-specific build and packaging steps
          (e.g., zipping, creating container image).
        - Cache validation and reuse if possible
        - Cache updates after successful build

        Args:
            package_build_step: Platform-specific build function for code package
            container_client: Docker client for building container images (if container deployment)
            container_build_step: Platform-specific build function for container deployments

        Returns:
            Tuple containing:
                - bool: Whether a new build was performed (False if cached)
                - str: Path to the built code package
                - bool: Whether this is a container deployment
                - str: Container URI (empty string if not container deployment)
        """
        # Skip build if files are up to date and user didn't enforce rebuild
        if self.is_cached and self.is_cached_valid:
            if self.container_deployment:
                if self._container_uri is None:
                    assert container_client is not None
                    self._container_uri = container_client.push_to_registry(
                        self.benchmark,
                        self.language_name,
                        self.language_version,
                        self.architecture,
                    )
                    self._cache_client.update_container_uri(
                        self._deployment_name,
                        self._benchmark,
                        self.language_name,
                        self.language_version,
                        self.architecture,
                        self._container_uri,
                    )
                self.logging.info(
                    "Using cached benchmark {} from container image {}".format(
                        self.benchmark, self.container_uri
                    )
                )
                return False, None, self.container_deployment, self.container_uri
            else:
                self.logging.info(
                    "Using cached benchmark {} at {}".format(self.benchmark, self.code_location)
                )
                return False, self.code_location, self.container_deployment, None

        msg = (
            "no cached code package/container."
            if not self.is_cached
            else "cached code package is not up to date/build enforced."
        )
        self.logging.info("Building benchmark {}. Reason: {}".format(self.benchmark, msg))
        # clear existing cache information
        self._code_package = None

        # create directory to be deployed
        if os.path.exists(self._output_dir):
            shutil.rmtree(self._output_dir)
        os.makedirs(self._output_dir)

        self.copy_code(self._output_dir)
        self.add_benchmark_data(self._output_dir)
        self.add_deployment_files(self._output_dir)
        self.add_deployment_package(self._output_dir)

        """
            We have two main build paths:
            (1) Code Package. There, we finish by installing dependencies,
                and let the platform figure out the details of code package,
                such as exact directory distribution.
            (2) Container build. There, we install all dependencies inside the container.
        """

        self._container_uri = None
        if self.container_deployment:
            assert container_client is not None

            repo_name = self._system_config.docker_repository()
            previous_version_image_name, current_version_image_name = self.builder_image_name()

            # Try current version build image first, fallback to previous version
            image_name = current_version_image_name
            current_available = False
            try:
                self._docker_client.images.get(f"{repo_name}:{current_version_image_name}")
                current_available = True
            except Exception:
                # Not available locally, try to pull it
                try:
                    self.logging.info(
                        f"Docker pull of build image {repo_name}:{current_version_image_name}"
                    )
                    self._docker_client.images.pull(repo_name, current_version_image_name)
                    current_available = True
                except Exception:
                    pass

            if not current_available:
                # Current version not available, try previous version
                try:
                    self._docker_client.images.get(f"{repo_name}:{previous_version_image_name}")
                    image_name = previous_version_image_name
                    self.logging.info(
                        f"Using previous version build image {previous_version_image_name} "
                        "(current version not available)"
                    )
                except Exception:
                    # Previous version not local, try to pull it
                    try:
                        self.logging.info(
                            f"Docker pull of build image {repo_name}:{previous_version_image_name}"
                        )
                        self._docker_client.images.pull(repo_name, previous_version_image_name)
                        image_name = previous_version_image_name
                        self.logging.info(
                            f"Using previous version build image {previous_version_image_name} "
                            "(current version not available)"
                        )
                    except Exception:
                        # Neither version available - use current and let build fail
                        self.logging.warning(
                            f"Neither current ({current_version_image_name}) nor previous "
                            f"({previous_version_image_name}) version build image available, "
                            "build may fail"
                        )

            """
                Generate custom Dockerfile for C++ benchmarks
            """
            if self.language == Language.CPP:
                from sebs.cpp_dependencies import CppDependencies

                template_path = os.path.join(
                    get_resource_path("dockerfiles"),
                    self._deployment_name,
                    "cpp",
                    "Dockerfile.function",
                )
                with open(template_path, "r") as f:
                    dockerfile_template = f.read()

                dockerfile_content = CppDependencies.generate_dockerfile(
                    self._benchmark_config._cpp_dependencies,
                    dockerfile_template,
                    self._system_config.version(),
                    previous_version=self._system_config.previous_version(),
                    docker_client=self._docker_client,
                    docker_repository=self._system_config.docker_repository(),
                    logger=self.logging,
                )
                dockerfile_path = os.path.join(self._output_dir, "Dockerfile")
                with open(dockerfile_path, "w") as f:
                    f.write(dockerfile_content)

                self.logging.info(
                    f"Generated custom Dockerfile for C++ benchmark with "
                    f"{len(self._benchmark_config._cpp_dependencies)} explicit dependencies"
                )

            _, self._container_uri, self._code_size = container_client.build_base_image(
                os.path.abspath(self._output_dir),
                self.language,
                self.language_version,
                self.architecture,
                self.benchmark,
                self.is_cached_valid,
                f"{repo_name}:{image_name}",
            )
            self.logging.info(
                f"Created function container {self._container_uri},"
                f" code package (source hash: {self.hash}), for run on {self._deployment_name}"
                f" with {self.language_name}:{self.language_version}"
            )

            """
                OpenWhisk requires a code package in addition to the container.
            """

            if container_build_step is not None:
                self._code_location, self._code_size = package_build_step(
                    os.path.abspath(self._output_dir),
                    self.language,
                    self.language_version,
                    self.architecture,
                    self.benchmark,
                    self.is_cached_valid,
                )

        else:
            self.install_dependencies(self._output_dir)

            self._code_location, self._code_size = package_build_step(
                os.path.abspath(self._output_dir),
                self.language,
                self.language_version,
                self.architecture,
                self.benchmark,
                self.is_cached_valid,
            )
            self.logging.info(
                (
                    "Created code package (source hash: {hash}), for run on {deployment}"
                    + " with {language}:{runtime}"
                ).format(
                    hash=self.hash,
                    deployment=self._deployment_name,
                    language=self.language_name,
                    runtime=self.language_version,
                )
            )

        """
            Update can handle both update of an existing cache structure
            or creating an entirely new one.
        """
        self._cache_client.update_code_package(self._deployment_name, self)
        self.query_cache()

        return (
            True,
            self._code_location,
            self._container_deployment,
            self._container_uri,
        )

    def prepare_input(
        self,
        system_resources: SystemResources,
        size: str,
        replace_existing: bool = False,
    ) -> Dict[str, str]:
        """Prepare benchmark input data and allocate cloud resources.

        Locates the benchmark's input generator module (`input.py`), determines
        storage requirements (object storage buckets, NoSQL tables), and invokes
        the `generate_input` function from the module to create and upload
        input data. Handles the setup of cloud storage buckets and NoSQL databases
        required by the benchmark.
        Updates the cache with storage details after successful preparation.

        Args:
            system_resources: Cloud system resources manager
            size: Benchmark workload size ('small', 'medium', 'large')
            replace_existing: Whether to replace existing input data

        Returns:
            Dict[str, str]: Input configuration for the benchmark function
        """
        if hasattr(self._benchmark_input_module, "buckets_count"):
            buckets = self._benchmark_input_module.buckets_count()
            storage = system_resources.get_storage(replace_existing)
            input, output = storage.benchmark_data(self.benchmark, buckets)

            self._uses_storage = len(input) > 0 or len(output) > 0

            storage_func = storage.uploader_func
            bucket = storage.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        else:
            input = []
            output = []
            storage_func = None
            bucket = None

        """
            Handle key-value storage.
            This part is optional - only selected benchmarks implement this.
        """
        if hasattr(self._benchmark_input_module, "allocate_nosql"):
            nosql_storage = system_resources.get_nosql_storage()
            for (
                name,
                table_properties,
            ) in self._benchmark_input_module.allocate_nosql().items():
                nosql_storage.create_benchmark_tables(
                    self._benchmark,
                    name,
                    table_properties["primary_key"],
                    table_properties.get("secondary_key"),
                )

            self._uses_nosql = True
            nosql_func = nosql_storage.write_to_table
        else:
            nosql_func = None

        # buckets = mod.buckets_count()
        # storage.allocate_buckets(self.benchmark, buckets)
        # Get JSON and upload data as required by benchmark
        input_config = self._benchmark_input_module.generate_input(
            self._benchmark_data_path,
            size,
            bucket,
            input,
            output,
            storage_func,
            nosql_func,
        )

        # Cache only once we data is in the cloud.
        if hasattr(self._benchmark_input_module, "buckets_count"):
            self._cache_client.update_storage(
                storage.deployment_name(),
                self._benchmark,
                {
                    "buckets": {
                        "input": storage.input_prefixes,
                        "output": storage.output_prefixes,
                        "input_uploaded": True,
                    }
                },
            )

        if hasattr(self._benchmark_input_module, "allocate_nosql"):
            nosql_storage.update_cache(self._benchmark)

        self._input_processed = True

        return input_config

    def validate_output(
        self, input_config: dict, output: dict, storage: Optional[PersistentStorage] = None
    ) -> str | None:
        """Validate benchmark output against expected values.

        Delegates to the benchmark's input module `validate_output` function
        if it is defined. Passes the optional storage client through when the
        module's validator declares a ``storage`` parameter. Logs a warning and
        returns an error message when no validation function is available.

        Args:
            input_config: The input configuration used to invoke the benchmark
            output: The output returned by the benchmark function handler
            storage: Optional persistent storage client for download-based checks

        Returns:
            None if validation passes, or a string describing the failure reason
        """
        if hasattr(self._benchmark_input_module, "validate_output"):
            fn = self._benchmark_input_module.validate_output
            return fn(self._benchmark_data_path, input_config, output, str(self._language), storage)

        self.logging.warning(f"Benchmark {self._benchmark} does not implement validate_output.")
        return f"Benchmark {self._benchmark} does not implement validate_output"

    def code_package_modify(self, filename: str, data: bytes) -> None:
        """
        Updates a specific file within the code package without rebuilding
        the entire package. Currently only supports ZIP archive packages.
        This is used in experiments that modify the size of input package.

        Does not support resizing containers or Azure deployments (non-ZIP).

        Args:
            filename: Name of the file to modify within the package
            data: New content for the file as bytes

        Raises:
            NotImplementedError: If the code package is not a ZIP archive
        """
        if not self.container_deployment and self.code_package_is_archive():
            assert self.code_location is not None
            self._update_zip(self.code_location, filename, data)
            new_size = self.code_package_recompute_size() / 1024.0 / 1024.0
            self.logging.info(f"Modified zip package {self.code_location}, new size {new_size} MB")
        else:
            raise NotImplementedError()

    def code_package_is_archive(self) -> bool:
        """Check if the code package is an archive file.

        Determines whether the code package is stored as an archive file
        (ZIP) rather than a directory structure.

        Returns:
            bool: True if package is a ZIP archive, False if it's a directory
        """

        if self.container_deployment:
            return False

        code_location = self.code_location
        assert code_location is not None
        if os.path.isfile(code_location):
            extension = os.path.splitext(code_location)[1]
            return extension in [".zip"]
        return False

    def code_package_recompute_size(self) -> float:
        """Recalculate the size of the code package file.

        Updates the internal size tracking after modifications to the
        code package file.

        Returns:
            float: Updated package size in bytes
        """
        if self.container_deployment:
            raise NotImplementedError()

        if self.code_location is None:
            raise RuntimeError("Code location is not set!")

        bytes_size = os.path.getsize(self.code_location)
        self._code_size = bytes_size
        return bytes_size

    @staticmethod
    def _update_zip(zipname: str, filename: str, data: bytes) -> None:
        """Update a file within a ZIP archive.

        Replaces the content of a specific file within a ZIP archive
        while preserving all other files and archive metadata.

        Creates a temporary zip file, copies all items from the original except
        the target file (if it exists), and adds/replaces the target file with
        new data. Finally, replaces the original zip with the temporary one.
        Based on method from:
        https://stackoverflow.com/questions/25738523/how-to-update-one-file-inside-zip-file-using-python

        Args:
            zipname: Path to the ZIP archive to modify
            filename: Name of the file to update within the archive
            data: New content for the file as bytes
        """
        import zipfile
        import tempfile

        # generate a temp file
        tmpfd, tmpname = tempfile.mkstemp(dir=os.path.dirname(zipname))
        os.close(tmpfd)

        # create a temp copy of the archive without filename
        with zipfile.ZipFile(zipname, "r") as zin:
            with zipfile.ZipFile(tmpname, "w") as zout:
                zout.comment = zin.comment  # preserve the comment
                for item in zin.infolist():
                    if item.filename != filename:
                        zout.writestr(item, zin.read(item.filename))

        # replace with the temp archive
        os.remove(zipname)
        os.rename(tmpname, zipname)

        # now add filename with its new data
        with zipfile.ZipFile(zipname, mode="a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(filename, data)


class BenchmarkModuleInterface:
    """Interface definition for benchmark input modules.
    Useful for static type hinting with mypy and documentation.

    This class defines the interface that benchmark input modules
    must implement to provide input data generation, storage allocation,
    and NoSQL database setup for benchmarks.

    All methods are static as they operate on benchmark data rather than
    instance state. Benchmark modules are dynamically loaded from the
    input.py file in each benchmark directory.
    """

    @staticmethod
    @abstractmethod
    def buckets_count() -> Tuple[int, int]:
        """Get the number of storage buckets required by the benchmark.

        Returns:
            Tuple[int, int]: Number of (input_buckets, output_buckets) needed
        """
        pass

    @staticmethod
    @abstractmethod
    def allocate_nosql() -> Dict[str, Dict[str, str]]:
        """Define NoSQL table requirements for the benchmark.

        Returns:
            Dict containing table definitions with primary and secondary keys:
            {
                'table_name': {
                    'primary_key': 'key_field_name',
                    'secondary_key': 'optional_secondary_key_name'
                }
            }
        """
        pass

    @staticmethod
    @abstractmethod
    def generate_input(
        data_dir: Optional[str],
        size: str,
        benchmarks_bucket: Optional[str],
        input_paths: List[str],
        output_paths: List[str],
        upload_func: Optional[Callable[[int, str, str], None]],
        nosql_func: Optional[
            Callable[[str, str, dict, Tuple[str, str], Optional[Tuple[str, str]]], None]
        ],
    ) -> Dict[str, str]:
        """Generate benchmark input data and configuration.

        Creates the input data files and configuration needed for benchmark
        execution, uploading data to cloud storage and NoSQL databases as needed.

        Args:
            data_dir: Directory containing benchmark data files
            size: Benchmark workload size ('small', 'medium', 'large')
            benchmarks_bucket: Name of the cloud storage bucket for data
            input_paths: List of input data paths in cloud storage
            output_paths: List of output data paths in cloud storage
            upload_func: Function for uploading files to cloud storage
            nosql_func: Function for writing data to NoSQL databases

        Returns:
            Dict[str, str]: Input configuration dictionary for the benchmark
        """
        pass

    @staticmethod
    def validate_output(
        data_dir: str | None,
        input_config: dict,
        output: dict,
        language: str,
        storage: Optional[PersistentStorage],
    ) -> str | None:
        """Validate benchmark output against expected values.

        Checks that the benchmark function's output is correct for the given
        input. This optional method can be implemented in each benchmark's
        input.py to enable output validation during regression testing.

        Args:
            data_dir: Directory containing benchmark data files (if exists)
            input_config: The input configuration used to invoke the benchmark
            output: The output returned by the benchmark function handler
            language: Benchmark implementation language (e.g., 'python', 'nodejs')
            storage: Storage interface for downloading output files if needed for validation

        Returns:
            None if validation passes, or a string describing the failure reason
        """
        return None


def load_benchmark_input(benchmark_path: str) -> BenchmarkModuleInterface:
    """Dynamically load the input module for a benchmark.

    Loads the input.py file from the benchmark directory and returns it
    as a module interface for generating benchmark input data.

    Args:
        benchmark_path: Path to the benchmark directory containing input.py

    Returns:
        BenchmarkModuleInterface: Loaded input module with benchmark-specific
            input generation functions

    Raises:
        FileNotFoundError: If input.py is not found in the benchmark directory
        ImportError: If the input module cannot be loaded
    """
    # Look for input generator file in the directory containing benchmark
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("input", os.path.join(benchmark_path, "input.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod  # type: ignore

# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Caching system for SeBS (Serverless Benchmarking Suite).

This module provides comprehensive caching functionality for the SeBS framework,
including configuration caching, code package management, function deployment
tracking, and storage resource management.

The Cache class manages persistent storage of benchmark configurations, compiled
code packages, Docker containers, deployed functions, and cloud resource
configurations to optimize repeated benchmark executions and deployments.

This class is essential for efficient benchmarking - we avoid regenerating
cloud resources, and we do not have to keep querying them every time
we start the benchmark. This is particularly important for cloud platforms
like Azure, where queries require CLI tool running in a container and can
take long time to resolve.

Example:
    Basic cache usage:
        cache = Cache("/path/to/cache", docker_client)
        config = cache.get_benchmark_config("aws", "110.dynamic-html")
        cache.add_code_package("aws", benchmark_instance)
"""

import collections.abc
import docker
import datetime
import json
import os
import shutil
import threading
import tempfile
from typing import Any, Callable, Dict, List, Mapping, Optional, TYPE_CHECKING  # noqa

from sebs.utils import LoggingBase, serialize

if TYPE_CHECKING:
    from sebs.benchmark import Benchmark
    from sebs.faas.function import Function


def update(d: Dict[str, Any], u: Mapping[str, Any]) -> Dict[str, Any]:
    """Recursively update nested dictionary with another dictionary.

    This function performs deep merge of two dictionaries, merging nested
    dictionary values rather than replacing them entirely.


    Args:
        d (Dict[str, Any]): The target dictionary to update.
        u (Mapping[str, Any]): The source dictionary with updates.

    Returns:
        Dict[str, Any]: The updated dictionary.
    """

    # https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def update_dict(cfg: Dict[str, Any], val: Any, keys: List[str]) -> None:
    """Update dictionary value at nested key path.

    Updates a nested dictionary by setting a value at a path specified
    by a list of keys. Creates intermediate dictionaries as needed.

    Args:
        cfg (Dict[str, Any]): The dictionary to update.
        val (Any): The value to set at the key path.
        keys (List[str]): List of keys forming the path to the target location.
    """

    def map_keys(obj: Dict[str, Any], val: Any, keys: List[str]) -> Dict[str, Any]:
        """Helper to construct the nested dictionary structure for the update.
        First element of `keys` becomes the key for the current level,
        and the value is either the final value (if no more keys),
        or a result of a recursive call to map the remaining keys.

        Args:
            obj: Main dictionary.
            val: value to insert
            keys: list of nested keys

        Returns:
            [TODO:return]
        """
        if len(keys):
            return {keys[0]: map_keys(obj, val, keys[1:])}
        else:
            return val

    update(cfg, map_keys(cfg, val, keys))


class Cache(LoggingBase):
    """Persistent caching system for SeBS benchmark configurations and deployments.

    This class provides comprehensive caching functionality for SeBS benchmarks,
    including configuration management, code package storage, function tracking,
    and cloud resource management. It uses a file-based cache system with
    thread-safe operations.

    Attributes:
        cached_config (Dict[str, Any]): In-memory cache of cloud configurations.
        config_updated (bool): Flag indicating if configuration needs to be saved.
        cache_dir (str): Absolute path to the cache directory.
        ignore_functions (bool): Flag to skip function caching operations.
        ignore_storage (bool): Flag to skip storage resource caching.
        docker_client (docker.DockerClient): Docker client for container operations.
    """

    _lock_registry_guard = threading.Lock()
    _lock_registry: Dict[str, threading.RLock] = {}

    def __init__(self, cache_dir: str, docker_client: docker.DockerClient) -> None:
        """Initialize the Cache with directory and Docker client.

        Sets up the cache directory structure and loads existing configurations.
        Creates the cache directory if it doesn't exist, otherwise loads
        existing cached configurations.

        Args:
            cache_dir (str): Path to the cache directory.
            docker_client (docker.DockerClient): Docker client for container operations.
        """
        super().__init__()
        self.cached_config: Dict[str, Any] = {}
        self.config_updated: bool = False
        self.docker_client = docker_client
        self.cache_dir = os.path.abspath(cache_dir)
        self.ignore_functions: bool = False
        self.ignore_storage: bool = False
        self._lock = self._cache_dir_lock(self.cache_dir)
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        else:
            self.load_config()

    @staticmethod
    def typename() -> str:
        """Get the typename for this cache.

        Returns:
            str: The cache type name.
        """
        return "Cache"

    @classmethod
    def _cache_dir_lock(cls, cache_dir: str) -> threading.RLock:
        """Return a shared lock for all Cache instances pointing at one cache dir."""
        with cls._lock_registry_guard:
            if cache_dir not in cls._lock_registry:
                cls._lock_registry[cache_dir] = threading.RLock()
            return cls._lock_registry[cache_dir]

    @staticmethod
    def _write_json_atomic(path: str, data: Any) -> None:
        """Atomically replace a JSON file after fully writing it to a temp file."""
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fp:
                json.dump(data, fp, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _write_serialized_atomic(path: str, data: Dict[str, Any]) -> None:
        """Atomically replace a JSON file using the SeBS serializer."""
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fp:
                fp.write(serialize(data))
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def load_config(self) -> None:
        """Load cached cloud configurations from disk.

        Reads configuration files for all supported cloud platforms from
        the cache directory and loads them into memory.
        """
        with self._lock:
            for cloud in ["azure", "aws", "gcp", "openwhisk", "local"]:
                cloud_config_file = os.path.join(self.cache_dir, "{}.json".format(cloud))
                if os.path.exists(cloud_config_file):
                    with open(cloud_config_file, "r") as f:
                        self.cached_config[cloud] = json.load(f)

    def get_config(self, cloud: str) -> Optional[Dict[str, Any]]:
        """Get cached configuration for a specific cloud provider.

        Args:
            cloud (str): Cloud provider name (e.g., 'aws', 'azure', 'gcp').

        Returns:
            Optional[Dict[str, Any]]: The cached configuration or None if not found.
        """
        return self.cached_config[cloud] if cloud in self.cached_config else None

    def update_config(self, val: Any, keys: List[str]) -> None:
        """Update configuration values at nested key path.

        Updates cached configuration by setting a value at the specified
        nested key path. Sets the config_updated flag to ensure changes
        are persisted to disk.

        Args:
            val (Any): New value to store.
            keys (List[str]): Array of consecutive keys for multi-level dictionary.
        """
        with self._lock:
            update_dict(self.cached_config, val, keys)
        self.config_updated = True

    def lock(self) -> None:
        """Acquire the cache lock for thread-safe operations."""
        self._lock.acquire()

    def unlock(self) -> None:
        """Release the cache lock."""
        self._lock.release()

    def shutdown(self) -> None:
        """Save cached configurations to disk if they were updated.

        Writes all updated cloud configurations back to their respective
        JSON files in the cache directory.
        """
        if self.config_updated:
            with self._lock:
                for cloud in ["azure", "aws", "gcp", "openwhisk", "local"]:
                    if cloud in self.cached_config:
                        cloud_config_file = os.path.join(self.cache_dir, "{}.json".format(cloud))
                        self.logging.info("Update cached config {}".format(cloud_config_file))
                        self._write_json_atomic(cloud_config_file, self.cached_config[cloud])

    def get_benchmark_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """Access cached configuration of a benchmark.

        Args:
            deployment (str): Deployment platform ('aws', 'azure', 'gcp', 'openwhisk', 'local').
            benchmark (str): Benchmark name (e.g., '110.dynamic-html').

        Returns:
            Optional[Dict[str, Any]]: Benchmark configuration or None if not found.
        """
        with self._lock:
            benchmark_dir = os.path.join(self.cache_dir, benchmark)
            if os.path.exists(benchmark_dir):
                config_file = os.path.join(benchmark_dir, "config.json")
                if os.path.exists(config_file):
                    with open(config_file, "r") as fp:
                        cfg = json.load(fp)
                        return cfg[deployment] if deployment in cfg else None
        return None

    def get_code_package(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        language_version: str,
        architecture: str,
    ) -> Optional[Dict[str, Any]]:
        """Access cached version of benchmark code package.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            language (str): Programming language.
            language_version (str): Language version.
            architecture (str): Target architecture.

        Returns:
            Optional[Dict[str, Any]]: Code package configuration or None if not found.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)

        key = f"{language_version}-{architecture}"
        if cfg and language in cfg and key in cfg[language]["code_package"]:
            return cfg[language]["code_package"][key]
        else:
            return None

    def get_container(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        language_version: str,
        architecture: str,
    ) -> Optional[Dict[str, Any]]:
        """Access cached container configuration for a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            language (str): Programming language.
            language_version (str): Language version.
            architecture (str): Target architecture.

        Returns:
            Optional[Dict[str, Any]]: Container configuration or None if not found.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)

        key = f"{language_version}-{architecture}"
        if cfg and language in cfg and key in cfg[language]["containers"]:
            return cfg[language]["containers"][key]
        else:
            return None

    def invalidate_all_container_uris(self, deployment: str) -> None:
        """Set image-uri to None for all cached containers of a deployment.

        Walks all benchmark directories and clears the image-uri field for every
        container entry under the given deployment. This forces a re-push to the
        registry on next use without invalidating the rest of the cached state.

        This function is used primarily after cleaning up cloud resources.

        Args:
            deployment (str): Deployment platform name.
        """
        with self._lock:
            if not os.path.exists(self.cache_dir):
                return

            for entry in os.listdir(self.cache_dir):
                config_path = os.path.join(self.cache_dir, entry, "config.json")
                if not os.path.exists(config_path):
                    continue

                with open(config_path, "r") as fp:
                    config = json.load(fp)

                dep_cfg = config.get(deployment)
                if dep_cfg is None:
                    continue

                modified = False
                for lang_cfg in dep_cfg.values():
                    if lang_cfg is None:
                        continue
                    containers = lang_cfg.get("containers")
                    if containers is None:
                        continue
                    for container_cfg in containers.values():
                        container_cfg["image-uri"] = None
                        modified = True

                if modified:
                    self._write_json_atomic(config_path, config)

    def update_container_uri(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        language_version: str,
        architecture: str,
        uri: str,
    ) -> None:
        """Update the image-uri for a specific cached container entry.

        Used when the image is cached locally, but needs to be pushed to
        the registry to be accessible for cloud deployment.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            language (str): Programming language.
            language_version (str): Language version.
            architecture (str): Target architecture.
            uri (str): New image URI to store.
        """
        with self._lock:
            config_path = os.path.join(self.cache_dir, benchmark, "config.json")
            if not os.path.exists(config_path):
                return

            with open(config_path, "r") as fp:
                config = json.load(fp)

            key = f"{language_version}-{architecture}"
            config[deployment][language]["containers"][key]["image-uri"] = uri

            self._write_json_atomic(config_path, config)

    def get_functions(
        self, deployment: str, benchmark: str, language: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached function configurations for a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            language (str): Programming language.

        Returns:
            Optional[Dict[str, Any]]: Function configurations or None if not found.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)
        if cfg and language in cfg and not self.ignore_functions:
            return cfg[language]["functions"]
        else:
            return None

    def get_all_functions(self, deployment: str) -> Dict[str, Any]:
        """Get all cached function configurations for a given deployment.

        Iterates all benchmarks and languages in the cache to collect every
        function deployed to the specified platform.

        Args:
            deployment (str): Deployment platform name

        Returns:
            Mapping of function name to function configuration,
            aggregated across benchmarks and languages.
        """
        result: Dict[str, Any] = {}

        if not os.path.exists(self.cache_dir) or self.ignore_functions:
            return result

        with self._lock:
            for entry in os.listdir(self.cache_dir):
                config_path = os.path.join(self.cache_dir, entry, "config.json")
                if not os.path.exists(config_path):
                    continue

                with open(config_path, "r") as fp:
                    config = json.load(fp)

                dep_cfg = config.get(deployment)
                if dep_cfg is None:
                    continue

                for lang_cfg in dep_cfg.values():
                    if lang_cfg is None:
                        continue

                    functions = lang_cfg.get("functions")
                    if functions is not None:
                        result.update(functions)

        return result

    def get_storage_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """Access cached storage configuration of a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.

        Returns:
            Optional[Dict[str, Any]]: Storage configuration or None if not found.
        """
        return self._get_resource_config(deployment, benchmark, "storage")

    def get_nosql_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """Access cached NoSQL configuration of a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.

        Returns:
            Optional[Dict[str, Any]]: NoSQL configuration or None if not found.
        """
        return self._get_resource_config(deployment, benchmark, "nosql")

    def get_nosql_configs(self, deployment: str) -> Dict[str, Any]:
        """Access cached NoSQL configuration for all benchmarks.

        Iterates all benchmark directories in the cache and merges their
        NoSQL table configurations for the given deployment into a single dict.

        Args:
            deployment (str): Deployment platform name.

        Returns:
            NoSQL configurations across all benchmarks
        """
        result: Dict[str, Any] = {}

        if not os.path.exists(self.cache_dir):
            return result

        with self._lock:
            for entry in os.listdir(self.cache_dir):
                config_path = os.path.join(self.cache_dir, entry, "config.json")
                if not os.path.exists(config_path):
                    continue

                with open(config_path, "r") as fp:
                    config = json.load(fp)

                dep_cfg = config.get(deployment)
                if dep_cfg is None:
                    continue

                nosql = dep_cfg.get("nosql")
                if nosql is not None:
                    result.update(nosql)

        return result

    def _get_resource_config(
        self, deployment: str, benchmark: str, resource: str
    ) -> Optional[Dict[str, Any]]:
        """Helper to retrieve a specific type of resource
        configuration from the benchmark's cache.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            resource (str): Resource type ('storage' or 'nosql').

        Returns:
            Optional[Dict[str, Any]]: Resource configuration or None if not found.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)
        return cfg[resource] if cfg and resource in cfg and not self.ignore_storage else None

    def update_storage(self, deployment: str, benchmark: str, config: Dict[str, Any]) -> None:
        """Update cached storage configuration for a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            config (Dict[str, Any]): Storage configuration to cache.
        """
        if self.ignore_storage:
            return

        self._update_resources(deployment, benchmark, "storage", config)

    def update_nosql(self, deployment: str, benchmark: str, config: Dict[str, Any]) -> None:
        """Update cached NoSQL configuration for a benchmark.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            config (Dict[str, Any]): NoSQL configuration to cache.
        """
        if self.ignore_storage:
            return
        self._update_resources(deployment, benchmark, "nosql", config)

    def remove_function(self, deployment: str, benchmark: str, language: str, function_name: str):
        """Remove a function entry from all benchmark cache configs.

        Args:
            function_name: function for removal
        """
        with self._lock:
            if not os.path.exists(self.cache_dir):
                return

            config_path = os.path.join(self.cache_dir, benchmark, "config.json")

            with open(config_path, "r") as fp:
                config = json.load(fp)

            if deployment not in config:
                return

            if language not in config[deployment]:
                return

            lang_cfg = config[deployment][language]
            if function_name not in lang_cfg["functions"]:
                return

            self.logging.info(f"Deleting function {function_name} from cache")
            del lang_cfg["functions"][function_name]

            self._write_json_atomic(config_path, config)

    def remove_storage(self, deployment: str):
        """Remove storage config entries across all benchmarks for a deployment.

        Args:
            deployment: cloud platform name
        """
        self._remove_resource_config(deployment, "storage")

    def remove_nosql(self, deployment: str):
        """Remove nosql config entries across all benchmarks for a deployment.

        Args:
            deployment: cloud platform name
        """
        self._remove_resource_config(deployment, "nosql")

    def _remove_resource_config(self, deployment: str, resource: str):
        """Remove a resource configuration entry from all benchmark cache configs.

        Args:
            deployment: Deployment platform name.
            resource: Resource type ('storage' or 'nosql').
        """
        with self._lock:
            if not os.path.exists(self.cache_dir):
                return

            for entry in os.listdir(self.cache_dir):
                config_path = os.path.join(self.cache_dir, entry, "config.json")
                if not os.path.exists(config_path):
                    continue

                with open(config_path, "r") as fp:
                    config = json.load(fp)

                if deployment in config and resource in config[deployment]:
                    del config[deployment][resource]
                    self._write_json_atomic(config_path, config)

    def get_config_key(self, keys: List[str]) -> Optional[Any]:
        """Return the value at a nested key path in the cached configuration.
        Does not throw an error if the key path does not exist.

        Args:
            keys: key path needed to access the config value

        Returns:
            The value at the specified key path, or None if not found.
        """
        with self._lock:
            cfg = self.cached_config
            for key in keys[:-1]:
                if not isinstance(cfg, dict) or key not in cfg:
                    return None
                cfg = cfg[key]
            if isinstance(cfg, dict):
                return cfg.get(keys[-1])
            return None

    def remove_config_key(self, keys: List[str]):
        """Removes a configuration entry nested within cache dictiariony.
        Used after deleting a specific cloud resource.

        Does not throw an error if the key path does not exist.

        Args:
            keys: key path needed to access the config value
        """
        with self._lock:
            cfg = self.cached_config
            for key in keys[:-1]:
                if not isinstance(cfg, dict) or key not in cfg:
                    return
                cfg = cfg[key]
            if isinstance(cfg, dict) and keys[-1] in cfg:
                del cfg[keys[-1]]
        self.config_updated = True

    def _update_resources(
        self, deployment: str, benchmark: str, resource: str, config: Dict[str, Any]
    ) -> None:
        """Internal helper to update a resource configuration (storage or NoSQL) in the cache.


        Since the benchmark data is prepared before creating and caching a function,
        it ensures the benchmark's cache directory exists and updates the `config.json` file
        within it.

        Args:
            deployment (str): Deployment platform name.
            benchmark (str): Benchmark name.
            resource (str): Resource type ('storage' or 'nosql').
            config (Dict[str, Any]): Resource configuration to cache.
        """
        if self.ignore_storage:
            return

        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        os.makedirs(benchmark_dir, exist_ok=True)

        with self._lock:
            config_file = os.path.join(benchmark_dir, "config.json")
            if os.path.exists(config_file):
                with open(config_file, "r") as fp:
                    cached_config = json.load(fp)
            else:
                cached_config = {}

            if deployment in cached_config:
                cached_config[deployment][resource] = config
            else:
                cached_config[deployment] = {resource: config}

            self._write_json_atomic(config_file, cached_config)

    def add_code_package(
        self,
        deployment_name: str,
        code_package: "Benchmark",
    ) -> None:
        """Add a new code package to the cache.

        Copies the code package (directory or zip file) into the cache structure.
        Records metadata (hash, size, location, timestamps, image details if container)
        in the benchmark's `config.json` within the cache.
        Handles both package and container deployments.

        Args:
            deployment_name (str): Name of the deployment platform.
            code_package (Benchmark): The benchmark code package to cache.

        Raises:
            RuntimeError: If cached application already exists for the deployment.
        """
        with self._lock:
            language = code_package.cache_language_key
            language_version = code_package.language_version
            architecture = code_package.architecture

            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)
            os.makedirs(benchmark_dir, exist_ok=True)

            package_type = "docker" if code_package.container_deployment else "package"
            # Check if cache directory for this deployment exist
            cached_dir = os.path.join(
                benchmark_dir,
                deployment_name,
                language,
                language_version,
                architecture,
                package_type,
            )

            if not os.path.exists(cached_dir):
                os.makedirs(cached_dir, exist_ok=True)

                language_config = code_package.serialize()
                if code_package.code_location is not None:
                    self.logging.info(
                        f"Caching code package created at {code_package.code_location}"
                    )
                    # copy code
                    if os.path.isdir(code_package.code_location):
                        cached_location = os.path.join(cached_dir, "code")
                        shutil.copytree(code_package.code_location, cached_location)

                    # copy zip file
                    else:
                        package_name = os.path.basename(code_package.code_location)
                        cached_location = os.path.join(cached_dir, package_name)
                        shutil.copy2(code_package.code_location, cached_dir)

                    # don't store absolute path to avoid problems with moving cache dir
                    relative_cached_loc = os.path.relpath(cached_location, self.cache_dir)
                    language_config["location"] = relative_cached_loc

                    self.logging.info(f"Updating cached code package {cached_location}")
                else:
                    self.logging.info(f"Caching container pushed to: {code_package.container_uri}")

                date = str(datetime.datetime.now())
                language_config["date"] = {
                    "created": date,
                    "modified": date,
                }

                key = f"{language_version}-{architecture}"
                if code_package.container_deployment:
                    image = self.docker_client.images.get(code_package.container_uri)
                    language_config["image-uri"] = code_package.container_uri
                    language_config["image-id"] = image.id

                    config = {
                        deployment_name: {
                            language: {
                                "containers": {key: language_config},
                                "code_package": {},
                                "functions": {},
                            }
                        }
                    }
                else:
                    config = {
                        deployment_name: {
                            language: {
                                "code_package": {key: language_config},
                                "containers": {},
                                "functions": {},
                            }
                        }
                    }

                # make sure to not replace other entries
                if os.path.exists(os.path.join(benchmark_dir, "config.json")):
                    with open(os.path.join(benchmark_dir, "config.json"), "r") as fp:
                        cached_config = json.load(fp)
                        if deployment_name in cached_config:
                            # language known, platform known, extend dictionary
                            if language in cached_config[deployment_name]:
                                if code_package.container_deployment:
                                    cached_config[deployment_name][language]["containers"][
                                        key
                                    ] = language_config
                                else:
                                    cached_config[deployment_name][language]["code_package"][
                                        key
                                    ] = language_config

                            # language unknown, platform known - add new dictionary
                            else:
                                cached_config[deployment_name][language] = config[deployment_name][
                                    language
                                ]
                        else:
                            # language unknown, platform unknown - add new dictionary
                            cached_config[deployment_name] = config[deployment_name]
                        config = cached_config
                self._write_json_atomic(os.path.join(benchmark_dir, "config.json"), config)

            else:
                # TODO: update
                raise RuntimeError(
                    "Cached application {} for {} already exists!".format(
                        code_package.benchmark, deployment_name
                    )
                )

    def update_code_package(
        self,
        deployment_name: str,
        code_package: "Benchmark",
    ) -> None:
        """Update an existing code package in the cache.

        Copies the new code package version over the old one. Updates metadata
        (hash, size, modification timestamp, image details if container) in the
        benchmark's `config.json`. If the cached package doesn't exist, adds it as a new package.

        Args:
            deployment_name (str): Name of the deployment platform.
            code_package (Benchmark): The benchmark code package to update.
        """
        with self._lock:
            language = code_package.cache_language_key
            language_version = code_package.language_version
            architecture = code_package.architecture
            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)

            package_type = "docker" if code_package.container_deployment else "package"
            # Check if cache directory for this deployment exist
            cached_dir = os.path.join(
                benchmark_dir,
                deployment_name,
                language,
                language_version,
                architecture,
                package_type,
            )

            config_location = os.path.join(benchmark_dir, "config.json")

            if not os.path.exists(config_location):
                self.add_code_package(deployment_name, code_package)
                return

            with open(config_location, "r") as fp:
                config = json.load(fp)
                date = str(datetime.datetime.now())

            """
                Check that a package of this type - code package or container - exists.
                A simple check of directory existence is insufficient, as we might have
                created a code package earlier (which creates a directory), but not a container.
            """
            key = f"{language_version}-{architecture}"
            if code_package.container_deployment:
                main_key = "containers"
            else:
                main_key = "code_package"

            package_exists = True
            try:
                config[deployment_name][language][main_key][key]
            except KeyError:
                package_exists = False

                """
                    We have no such cache entry - fallback.
                    However, we still have directory, a possible leftover after crash.
                    Whatever was left, we remove it since we have no information what is there.
                """
                if os.path.exists(cached_dir):
                    shutil.rmtree(cached_dir)

            if package_exists:
                if code_package.code_location is not None:
                    self.logging.info(
                        f"Caching code package created at {code_package.code_location}"
                    )
                    # copy code
                    if os.path.isdir(code_package.code_location):
                        cached_location = os.path.join(cached_dir, "code")
                        # could be replaced with dirs_exists_ok in copytree
                        # available in 3.8
                        shutil.rmtree(cached_location)
                        shutil.copytree(src=code_package.code_location, dst=cached_location)

                    # copy zip file
                    else:
                        package_name = os.path.basename(code_package.code_location)
                        cached_location = os.path.join(cached_dir, package_name)
                        if code_package.code_location != cached_location:
                            shutil.copy2(code_package.code_location, cached_dir)

                    self.logging.info(f"Updated cached code package {cached_location}")
                else:
                    self.logging.info(f"Caching container pushed to: {code_package.container_uri}")

                config[deployment_name][language][main_key][key]["date"]["modified"] = date
                config[deployment_name][language][main_key][key]["hash"] = code_package.hash
                config[deployment_name][language][main_key][key]["size"] = code_package.code_size

                if code_package.container_deployment:
                    image = self.docker_client.images.get(code_package.container_uri)
                    config[deployment_name][language][main_key][key]["image-id"] = image.id
                    config[deployment_name][language][main_key][key][
                        "image-uri"
                    ] = code_package.container_uri

                self._write_json_atomic(os.path.join(benchmark_dir, "config.json"), config)
            else:
                self.add_code_package(deployment_name, code_package)

    def add_function(
        self,
        deployment_name: str,
        language_name: str,
        code_package: "Benchmark",
        function: "Function",
    ) -> None:
        """Add new function to cache.

        Caches a deployed function configuration for a benchmark. Links the
        function to its corresponding code package.

        Args:
            deployment_name (str): Name of the deployment platform.
            language_name (str): Programming language name.
            code_package (Benchmark): The benchmark code package.
            function (Function): The deployed function to cache.

        Raises:
            RuntimeError: If code package doesn't exist in cache.
        """
        if self.ignore_functions:
            return
        with self._lock:
            benchmark_dir = os.path.join(self.cache_dir, code_package.benchmark)
            language = code_package.cache_language_key
            cache_config = os.path.join(benchmark_dir, "config.json")

            if os.path.exists(cache_config):
                functions_config: Dict[str, Any] = {function.name: {**function.serialize()}}

                with open(cache_config, "r") as fp:
                    cached_config = json.load(fp)
                    if "functions" not in cached_config[deployment_name][language]:
                        cached_config[deployment_name][language]["functions"] = functions_config
                    else:
                        cached_config[deployment_name][language]["functions"].update(
                            functions_config
                        )
                    config = cached_config
                self._write_serialized_atomic(cache_config, config)
            else:
                raise RuntimeError(
                    "Can't cache function {} for a non-existing code package!".format(function.name)
                )

    def update_function(self, function: "Function") -> None:
        """Update an existing function in the cache.

        Updates cached function configuration with new metadata. Searches
        across all deployments and languages to find the function by name.

        Args:
            function (Function): The function with updated configuration.

        Raises:
            RuntimeError: If function's code package doesn't exist in cache.
        """
        if self.ignore_functions:
            return
        with self._lock:
            benchmark_dir = os.path.join(self.cache_dir, function.benchmark)
            cache_config = os.path.join(benchmark_dir, "config.json")

            if os.path.exists(cache_config):
                with open(cache_config, "r") as fp:
                    cached_config = json.load(fp)
                    for deployment, cfg in cached_config.items():
                        for language, cfg2 in cfg.items():
                            if "functions" not in cfg2:
                                continue
                            for name, func in cfg2["functions"].items():
                                if name == function.name:
                                    cached_config[deployment][language]["functions"][
                                        name
                                    ] = function.serialize()
                self._write_serialized_atomic(cache_config, cached_config)
            else:
                raise RuntimeError(
                    "Can't cache function {} for a non-existing code package!".format(function.name)
                )

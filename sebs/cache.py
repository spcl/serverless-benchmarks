# https://stackoverflow.com/questions/3232943/update-value-of-a-nested-dictionary-of-varying-depth
import collections.abc
import docker
import datetime
import json
import os
import shutil
import threading
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING  # noqa

from sebs.utils import LoggingBase, serialize

if TYPE_CHECKING:
    from sebs.benchmark import Benchmark
    from sebs.faas.function import Function


def update(d: dict, u: dict) -> dict:
    """
    Recursively update a dictionary `d` with values from dictionary `u`.

    If a key exists in both dictionaries and both values are mappings (dictionaries),
    the function recursively updates the nested dictionary. Otherwise, the value
    from `u` overwrites the value in `d`.

    :param d: The dictionary to be updated.
    :param u: The dictionary with new values.
    :return: The updated dictionary `d`.
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def update_dict(cfg: dict, val: Any, keys: List[str]):
    """
    Update a nested dictionary `cfg` at a path specified by `keys` with `val`.

    Constructs the nested dictionary structure if it doesn't exist.

    :param cfg: The dictionary to update.
    :param val: The value to set at the nested path.
    :param keys: A list of keys representing the path to the value.
    """
    def map_keys_recursive(current_keys: List[str]) -> Any: # Renamed inner map_keys
        if len(current_keys):
            # Recursively build the dictionary structure
            return {current_keys[0]: map_keys_recursive(current_keys[1:])}
        else:
            # Base case: return the value to be set
            return val
    # Start the recursive update
    update(cfg, map_keys_recursive(keys))


class Cache(LoggingBase):
    """
    Manages caching of SeBS configurations, benchmark code packages, and function details.

    The cache is stored on the local filesystem in a directory specified by `cache_dir`.
    It helps avoid redundant building of code packages and re-fetching of cloud resource
    details across SeBS runs. Thread safety for cache access is managed by an RLock.
    """
    cached_config: Dict[str, Any] = {} # Stores loaded configurations for different clouds
    config_updated: bool = False
    """Flag indicating if the in-memory `cached_config` has been modified and needs saving."""

    def __init__(self, cache_dir: str, docker_client: docker.DockerClient):
        """
        Initialize the Cache instance.

        Creates the cache directory if it doesn't exist and loads existing
        cached configurations from JSON files (one per cloud provider).

        :param cache_dir: Path to the directory where cache files are stored.
        :param docker_client: Docker client instance (used for some cache operations like image details).
        """
        super().__init__()
        self.docker_client = docker_client
        self.cache_dir = os.path.abspath(cache_dir)
        self.ignore_functions: bool = False # If True, function caching is bypassed
        self.ignore_storage: bool = False   # If True, storage configuration caching is bypassed
        self._lock = threading.RLock() # For thread-safe access to cache files and memory
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        # Load existing config from files on initialization
        self.load_config()

    @staticmethod
    def typename() -> str:
        """Return the type name of this class (used for logging context)."""
        # This seems to be a placeholder or misnamed, as Cache is not a Benchmark.
        # It should probably be "Cache" or similar if used for logging context.
        return "Cache" # Changed from "Benchmark" for clarity

    def load_config(self):
        """
        Load cached configurations for all supported cloud providers from their
        respective JSON files in the cache directory into `self.cached_config`.
        """
        with self._lock:
            for cloud_provider in ["azure", "aws", "gcp", "openwhisk", "local"]:
                config_file_path = os.path.join(self.cache_dir, f"{cloud_provider}.json")
                if os.path.exists(config_file_path):
                    try:
                        with open(config_file_path, "r") as f:
                            self.cached_config[cloud_provider] = json.load(f)
                    except json.JSONDecodeError as e:
                        self.logging.error(f"Error decoding JSON from cache file {config_file_path}: {e}")
                        # Decide behavior: skip this file, delete it, or raise error?
                        # For now, it will just not load this specific cache.
                # else:
                    # self.logging.debug(f"Cache file for {cloud_provider} not found at {config_file_path}.")


    def get_config(self, cloud: str) -> Optional[Dict[str, Any]]:
        """
        Get the cached configuration for a specific cloud provider.

        :param cloud: Name of the cloud provider (e.g., "aws", "local").
        :return: The cached configuration dictionary, or None if not found.
        """
        return self.cached_config.get(cloud)

    def update_config(self, val: Any, keys: List[str]):
        """
        Update a value in the in-memory `cached_config` at a nested path specified by `keys`.

        Sets `self.config_updated` to True to indicate that changes need to be
        written to disk on shutdown.

        :param val: The new value to store.
        :param keys: A list of strings representing the path to the value in the nested dictionary.
                     Example: `["aws", "resources", "region"]`
        """
        with self._lock:
            update_dict(self.cached_config, val, keys)
        self.config_updated = True

    def lock(self):
        """Acquire the reentrant lock for thread-safe cache operations."""
        self._lock.acquire()

    def unlock(self):
        """Release the reentrant lock."""
        self._lock.release()

    def shutdown(self):
        """
        Write any updated configurations back to their respective JSON files in the cache directory.
        This is typically called at the end of a SeBS run.
        """
        if self.config_updated:
            with self._lock: # Ensure thread safety during write
                for cloud_provider, config_data in self.cached_config.items():
                    config_file_path = os.path.join(self.cache_dir, f"{cloud_provider}.json")
                    self.logging.info(f"Updating cached config file: {config_file_path}")
                    try:
                        with open(config_file_path, "w") as out_f:
                            json.dump(config_data, out_f, indent=2)
                    except IOError as e:
                        self.logging.error(f"Error writing cache file {config_file_path}: {e}")
            self.config_updated = False # Reset flag after saving

    def get_benchmark_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """
        Access cached configuration specific to a benchmark and deployment.

        Reads `config.json` from the benchmark's cache directory.

        :param deployment: Name of the deployment (e.g., "aws", "local").
        :param benchmark: Name of the benchmark.
        :return: The deployment-specific part of the benchmark's cached config, or None.
        """
        benchmark_config_path = os.path.join(self.cache_dir, benchmark, "config.json")
        if os.path.exists(benchmark_config_path):
            try:
                with open(benchmark_config_path, "r") as fp:
                    cfg = json.load(fp)
                    return cfg.get(deployment)
            except json.JSONDecodeError as e:
                self.logging.error(f"Error decoding JSON from {benchmark_config_path}: {e}")
        return None

    def get_code_package(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        language_version: str,
        architecture: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached information about a benchmark's code package.

        Looks for a non-containerized code package.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param language: Programming language name.
        :param language_version: Language runtime version.
        :param architecture: CPU architecture.
        :return: Dictionary with code package details (hash, size, location) or None.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)
        key = f"{language_version}-{architecture}"
        # Path in cache: {deployment}.{language}.code_package.{key}
        return cfg.get(language, {}).get("code_package", {}).get(key) if cfg else None


    def get_container(
        self,
        deployment: str,
        benchmark: str,
        language: str,
        language_version: str,
        architecture: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached information about a benchmark's Docker container image.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param language: Programming language name.
        :param language_version: Language runtime version.
        :param architecture: CPU architecture.
        :return: Dictionary with container image details (hash, size, image-uri, image-id) or None.
        """
        cfg = self.get_benchmark_config(deployment, benchmark)
        key = f"{language_version}-{architecture}"
        # Path in cache: {deployment}.{language}.containers.{key}
        return cfg.get(language, {}).get("containers", {}).get(key) if cfg else None

    def get_functions(
        self, deployment: str, benchmark: str, language: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached information about deployed functions for a benchmark.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param language: Programming language name.
        :return: Dictionary of cached function details, keyed by function name, or None.
        """
        if self.ignore_functions:
            return None
        cfg = self.get_benchmark_config(deployment, benchmark)
        # Path in cache: {deployment}.{language}.functions
        return cfg.get(language, {}).get("functions") if cfg else None


    def get_storage_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """
        Access cached storage configuration for a specific benchmark and deployment.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :return: Cached storage configuration dictionary, or None if not found.
        """
        return self._get_resource_config(deployment, benchmark, "storage")

    def get_nosql_config(self, deployment: str, benchmark: str) -> Optional[Dict[str, Any]]:
        """
        Access cached NoSQL storage configuration for a specific benchmark and deployment.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :return: Cached NoSQL storage configuration dictionary, or None if not found.
        """
        return self._get_resource_config(deployment, benchmark, "nosql")

    def _get_resource_config(
        self, deployment: str, benchmark: str, resource_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Helper to retrieve a specific type of resource configuration from the benchmark's cache.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param resource_type: The type of resource ("storage" or "nosql").
        :return: The resource configuration dictionary, or None.
        """
        if self.ignore_storage: # Applies to both storage and nosql types
            return None
        cfg = self.get_benchmark_config(deployment, benchmark)
        return cfg.get(resource_type) if cfg else None


    def update_storage(self, deployment: str, benchmark: str, config_data: dict):
        """
        Update the cached storage configuration for a benchmark.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param config_data: New storage configuration data to cache.
        """
        if self.ignore_storage:
            return
        self._update_resources(deployment, benchmark, "storage", config_data)

    def update_nosql(self, deployment: str, benchmark: str, config_data: dict):
        """
        Update the cached NoSQL storage configuration for a benchmark.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param config_data: New NoSQL configuration data to cache.
        """
        if self.ignore_storage:
            return
        self._update_resources(deployment, benchmark, "nosql", config_data)

    def _update_resources(
        self, deployment: str, benchmark: str, resource_key: str, config_data: dict
    ):
        """
        Internal helper to update a resource configuration (storage or NoSQL) in the cache.

        Ensures the benchmark's cache directory exists and updates the `config.json` file
        within it. This method is called when preparing benchmark data before function caching.

        :param deployment: Deployment name.
        :param benchmark: Benchmark name.
        :param resource_key: Key for the resource type ("storage" or "nosql").
        :param config_data: Configuration data to save.
        """
        # This method is called when input data is prepared, before function itself might be cached.
        # Thus, the benchmark's config.json might not exist or might not have the deployment section yet.
        benchmark_dir = os.path.join(self.cache_dir, benchmark)
        os.makedirs(benchmark_dir, exist_ok=True)
        benchmark_config_path = os.path.join(benchmark_dir, "config.json")

        with self._lock:
            cached_benchmark_config: Dict[str, Any] = {}
            if os.path.exists(benchmark_config_path):
                try:
                    with open(benchmark_config_path, "r") as fp:
                        cached_benchmark_config = json.load(fp)
                except json.JSONDecodeError:
                    self.logging.error(f"Corrupted cache file at {benchmark_config_path}. Re-initializing.")
            
            # Ensure structure exists: cached_benchmark_config[deployment][resource_key]
            if deployment not in cached_benchmark_config:
                cached_benchmark_config[deployment] = {}
            cached_benchmark_config[deployment][resource_key] = config_data

            with open(benchmark_config_path, "w") as fp:
                json.dump(cached_benchmark_config, fp, indent=2)


    def add_code_package(
        self,
        deployment_name: str,
        code_package_benchmark: "Benchmark", # Renamed for clarity
    ):
        """
        Add a new benchmark code package to the cache.

        Copies the code package (directory or zip file) into the cache structure.
        Records metadata (hash, size, location, timestamps, image details if container)
        in the benchmark's `config.json` within the cache.

        :param deployment_name: Name of the deployment.
        :param code_package_benchmark: The Benchmark object representing the code package.
        :raises RuntimeError: If a cached entry for this package already exists (use update instead).
        """
        with self._lock:
            benchmark_name = code_package_benchmark.benchmark
            language_name = code_package_benchmark.language_name
            language_version = code_package_benchmark.language_version
            architecture = code_package_benchmark.architecture
            is_container = code_package_benchmark.container_deployment

            benchmark_cache_dir = os.path.join(self.cache_dir, benchmark_name)
            os.makedirs(benchmark_cache_dir, exist_ok=True)

            package_subdir_type = "container" if is_container else "package"
            # Path for this specific variant of the code package
            variant_cache_dir = os.path.join(
                benchmark_cache_dir, deployment_name, language_name,
                language_version, architecture, package_subdir_type
            )

            if os.path.exists(variant_cache_dir):
                 # This check might be too strict if we just want to ensure the record is there.
                 # Original code raised error. Consider logging a warning and proceeding if just metadata update.
                raise RuntimeError(
                    f"Attempting to add an already cached code package for {benchmark_name} "
                    f"({deployment_name}/{language_name}/{language_version}/{architecture}/{package_subdir_type}). "
                    "Use update_code_package if an update is intended."
                )
            os.makedirs(variant_cache_dir, exist_ok=True)

            # Copy code to cache
            final_cached_code_path: str
            if os.path.isdir(code_package_benchmark.code_location):
                final_cached_code_path = os.path.join(variant_cache_dir, "code")
                shutil.copytree(code_package_benchmark.code_location, final_cached_code_path)
            else: # Assuming it's a file (zip)
                file_basename = os.path.basename(code_package_benchmark.code_location)
                final_cached_code_path = os.path.join(variant_cache_dir, file_basename)
                shutil.copy2(code_package_benchmark.code_location, final_cached_code_path) # Use final_cached_code_path for dest

            # Prepare metadata for cache entry
            package_metadata = code_package_benchmark.serialize()
            # Store path relative to cache_dir
            package_metadata["location"] = os.path.relpath(final_cached_code_path, self.cache_dir)
            current_time_str = str(datetime.datetime.now())
            package_metadata["date"] = {"created": current_time_str, "modified": current_time_str}

            version_arch_key = f"{language_version}-{architecture}"
            if is_container:
                docker_image = self.docker_client.images.get(code_package_benchmark.container_uri)
                package_metadata["image-uri"] = code_package_benchmark.container_uri
                package_metadata["image-id"] = docker_image.id
                new_entry_structure = {"containers": {version_arch_key: package_metadata}}
            else:
                new_entry_structure = {"code_package": {version_arch_key: package_metadata}}

            # Update benchmark's config.json
            benchmark_config_path = os.path.join(benchmark_cache_dir, "config.json")
            master_config: Dict[str, Any] = {}
            if os.path.exists(benchmark_config_path):
                with open(benchmark_config_path, "r") as fp:
                    try:
                        master_config = json.load(fp)
                    except json.JSONDecodeError:
                        self.logging.error(f"Corrupted cache file {benchmark_config_path}. Re-initializing.")
            
            # Merge new entry carefully
            deployment_entry = master_config.setdefault(deployment_name, {})
            language_entry = deployment_entry.setdefault(language_name, {"code_package": {}, "containers": {}, "functions": {}})
            
            if is_container:
                language_entry.setdefault("containers", {})[version_arch_key] = package_metadata
            else:
                language_entry.setdefault("code_package", {})[version_arch_key] = package_metadata

            with open(benchmark_config_path, "w") as fp:
                json.dump(master_config, fp, indent=2)


    def update_code_package(
        self,
        deployment_name: str,
        code_package_benchmark: "Benchmark", # Renamed for clarity
    ):
        """
        Update an existing benchmark code package in the cache.

        Copies the new code package version over the old one. Updates metadata
        (hash, size, modification timestamp, image details if container) in the
        benchmark's `config.json`. If the package was not previously cached,
        it calls `add_code_package` instead.

        :param deployment_name: Name of the deployment.
        :param code_package_benchmark: The Benchmark object with updated code/details.
        """
        with self._lock:
            benchmark_name = code_package_benchmark.benchmark
            language_name = code_package_benchmark.language_name
            language_version = code_package_benchmark.language_version
            architecture = code_package_benchmark.architecture
            is_container = code_package_benchmark.container_deployment
            benchmark_cache_dir = os.path.join(self.cache_dir, benchmark_name)

            package_subdir_type = "container" if is_container else "package"
            variant_cache_dir = os.path.join(
                benchmark_cache_dir, deployment_name, language_name,
                language_version, architecture, package_subdir_type
            )

            if not os.path.exists(variant_cache_dir):
                # If the specific variant cache dir doesn't exist, it's effectively a new add.
                self.logging.info(f"Cache directory {variant_cache_dir} not found. Adding as new code package.")
                self.add_code_package(deployment_name, code_package_benchmark)
                return

            # Directory exists, proceed with update
            # Copy new code over old cached code
            # Assuming code_package_benchmark.code_location points to the *new* source to be cached
            if os.path.isdir(code_package_benchmark.code_location):
                cached_code_path = os.path.join(variant_cache_dir, "code")
                if os.path.exists(cached_code_path): # Remove old before copying new
                    shutil.rmtree(cached_code_path)
                shutil.copytree(code_package_benchmark.code_location, cached_code_path)
            else: # It's a file (zip)
                file_basename = os.path.basename(code_package_benchmark.code_location)
                cached_code_path = os.path.join(variant_cache_dir, file_basename)
                # Ensure source and dest are different if shutil.copy2 is used,
                # or handle potential issues if they are the same (though unlikely here).
                if os.path.abspath(code_package_benchmark.code_location) != os.path.abspath(cached_code_path):
                    shutil.copy2(code_package_benchmark.code_location, cached_code_path)
            
            # Update metadata in config.json
            benchmark_config_path = os.path.join(benchmark_cache_dir, "config.json")
            if not os.path.exists(benchmark_config_path):
                # This case should ideally be handled by add_code_package if we reach here due to missing dir
                self.logging.error(f"Benchmark config file {benchmark_config_path} missing during update. This indicates an inconsistent cache state.")
                # Attempt to add as new, though this might indicate a deeper issue.
                self.add_code_package(deployment_name, code_package_benchmark)
                return

            with open(benchmark_config_path, "r+") as fp: # Open for read and write
                master_config = json.load(fp)
                current_time_str = str(datetime.datetime.now())
                version_arch_key = f"{language_version}-{architecture}"
                
                main_key = "containers" if is_container else "code_package"
                
                # Navigate to the specific package entry to update
                try:
                    package_entry = master_config[deployment_name][language_name][main_key][version_arch_key]
                except KeyError:
                    self.logging.error(f"Cache structure error for {benchmark_name} during update. Attempting to add as new.")
                    # Fallback to add_code_package if structure is missing
                    # Release lock before calling another method that acquires it
                    fp.close() # Close file before calling add_code_package
                    self.add_code_package(deployment_name, code_package_benchmark)
                    return

                package_entry["date"]["modified"] = current_time_str
                package_entry["hash"] = code_package_benchmark.hash
                package_entry["size"] = code_package_benchmark.code_size
                package_entry["location"] = os.path.relpath(cached_code_path, self.cache_dir)


                if is_container:
                    docker_image = self.docker_client.images.get(code_package_benchmark.container_uri)
                    package_entry["image-id"] = docker_image.id
                    package_entry["image-uri"] = code_package_benchmark.container_uri
                
                # Write changes back
                fp.seek(0) # Rewind to overwrite
                json.dump(master_config, fp, indent=2)
                fp.truncate() # Remove any trailing old data if new data is shorter

    def add_function(
        self,
        deployment_name: str,
        language_name: str, # Already available from code_package_benchmark
        code_package_benchmark: "Benchmark", # Renamed for clarity
        function_to_add: "Function", # Renamed for clarity
    ):
        """
        Add a new function's deployment details to the cache.

        Stores the serialized function information under its benchmark, deployment,
        and language in the respective `config.json`.

        :param deployment_name: Name of the deployment.
        :param language_name: Name of the programming language (redundant, use from code_package_benchmark).
        :param code_package_benchmark: The Benchmark object this function belongs to.
        :param function_to_add: The Function object to cache.
        :raises RuntimeError: If the benchmark's code package is not already cached.
        """
        if self.ignore_functions:
            return
        with self._lock:
            benchmark_name = code_package_benchmark.benchmark
            # Language name from code_package_benchmark is more reliable
            actual_language_name = code_package_benchmark.language_name
            benchmark_cache_dir = os.path.join(self.cache_dir, benchmark_name)
            benchmark_config_path = os.path.join(benchmark_cache_dir, "config.json")

            if not os.path.exists(benchmark_config_path):
                # This implies that the code package itself was not cached first.
                raise RuntimeError(
                    f"Cannot cache function {function_to_add.name} for benchmark {benchmark_name} "
                    "because its code package is not cached. Call add_code_package first."
                )

            with open(benchmark_config_path, "r+") as fp: # Read and write mode
                master_config = json.load(fp)
                
                # Ensure path exists: master_config[deployment_name][actual_language_name]["functions"]
                deployment_entry = master_config.setdefault(deployment_name, {})
                language_entry = deployment_entry.setdefault(actual_language_name, {"code_package": {}, "containers": {}, "functions": {}})
                functions_dict = language_entry.setdefault("functions", {})
                
                functions_dict[function_to_add.name] = function_to_add.serialize()
                
                fp.seek(0)
                json.dump(master_config, fp, indent=2)
                fp.truncate()


    def update_function(self, function_to_update: "Function"): # Renamed for clarity
        """
        Update an existing function's details in the cache.

        Finds the cached entry for the function and replaces it with the
        serialized state of the provided Function object.

        :param function_to_update: The Function object with updated details.
        :raises RuntimeError: If the benchmark's code package or the function entry is not found in cache.
        """
        if self.ignore_functions:
            return
        with self._lock:
            benchmark_name = function_to_update.benchmark
            # Assuming function's config holds its language details correctly
            language_name = function_to_update.config.runtime.language.value
            
            benchmark_cache_dir = os.path.join(self.cache_dir, benchmark_name)
            benchmark_config_path = os.path.join(benchmark_cache_dir, "config.json")

            if not os.path.exists(benchmark_config_path):
                raise RuntimeError(
                    f"Cannot update function {function_to_update.name} in cache: "
                    f"config file for benchmark {benchmark_name} does not exist."
                )

            with open(benchmark_config_path, "r+") as fp: # Read and write
                master_config = json.load(fp)
                updated = False
                # Iterate to find the correct deployment and language for this function
                # This is a bit indirect; ideally, we'd know the deployment_name here.
                # Assuming a function name is unique across deployments for a benchmark/language,
                # or that this update is called in a context where deployment_name is implicit.
                for deployment_key, deployment_data in master_config.items():
                    if language_name in deployment_data:
                        functions_dict = deployment_data[language_name].get("functions", {})
                        if function_to_update.name in functions_dict:
                            functions_dict[function_to_update.name] = function_to_update.serialize()
                            updated = True
                            break # Found and updated
                    if updated:
                        break
                
                if updated:
                    fp.seek(0)
                    json.dump(master_config, fp, indent=2)
                    fp.truncate()
                else:
                    self.logging.warning(
                       f"Function {function_to_update.name} not found in cache for benchmark "
                       f"{benchmark_name} under any deployment for language {language_name}. "
                       "Consider using add_function if this is a new function for a deployment."
                    )

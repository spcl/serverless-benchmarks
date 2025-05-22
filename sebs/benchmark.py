import glob
import hashlib
import json
import os
import shutil
import subprocess
from abc import abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

import docker

from sebs.config import SeBSConfig
from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.resources import SystemResources
from sebs.utils import find_benchmark, project_absolute_path, LoggingBase
from sebs.types import BenchmarkModule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebs.experiments.config import Config as ExperimentConfig
    from sebs.faas.function import Language


"""
This module defines the `Benchmark` and `BenchmarkConfig` classes, which are
central to defining, configuring, and managing benchmarks within the SeBS framework.
It also includes an interface for benchmark input generation modules and a helper
function to load them.
"""


class BenchmarkConfig:
    """
    Configuration for a specific benchmark.

    Stores settings like timeout, memory allocation, supported languages,
    and required SeBS modules (e.g., for storage or NoSQL access).

    Attributes:
        _timeout: Execution timeout for the benchmark function in seconds.
        _memory: Memory allocated to the benchmark function in MB.
        _languages: List of supported programming languages (Language enums).
        _modules: List of SeBS modules required by the benchmark.
    """
    def __init__(
        self, timeout: int, memory: int, languages: List["Language"], modules: List[BenchmarkModule]
    ):
        """
        Initialize a BenchmarkConfig instance.

        :param timeout: Function execution timeout in seconds.
        :param memory: Memory allocation for the function in MB.
        :param languages: List of supported Language enums.
        :param modules: List of BenchmarkModule enums required by the benchmark.
        """
        self._timeout = timeout
        self._memory = memory
        self._languages = languages
        self._modules = modules

    @property
    def timeout(self) -> int:
        """Execution timeout for the benchmark function in seconds."""
        return self._timeout

    @timeout.setter
    def timeout(self, val: int):
        """Set the execution timeout."""
        self._timeout = val

    @property
    def memory(self) -> int:
        """Memory allocated to the benchmark function in MB."""
        return self._memory

    @memory.setter
    def memory(self, val: int):
        """Set the memory allocation."""
        self._memory = val

    @property
    def languages(self) -> List["Language"]:
        """List of supported programming languages for this benchmark."""
        return self._languages

    @property
    def modules(self) -> List[BenchmarkModule]:
        """List of SeBS modules (e.g., storage, nosql) required by this benchmark."""
        return self._modules

    # FIXME: 3.7+ python with future annotations - Noted from original.
    @staticmethod
    def deserialize(json_object: dict) -> "BenchmarkConfig":
        """
        Deserialize a BenchmarkConfig object from a JSON-like dictionary.

        :param json_object: Dictionary containing benchmark configuration data.
        :return: A BenchmarkConfig instance.
        """
        from sebs.faas.function import Language # Local import to avoid circular dependency at module level

        return BenchmarkConfig(
            json_object["timeout"],
            json_object["memory"],
            [Language.deserialize(x) for x in json_object["languages"]],
            [BenchmarkModule(x) for x in json_object["modules"]],
        )


class Benchmark(LoggingBase):
    """
    Represents a benchmark, managing its code, configuration, and deployment package.

    Handles the lifecycle of a benchmark's code package, including building it
    (which involves copying source files, adding deployment-specific wrappers and
    dependencies, and installing dependencies via Docker), caching the package,
    and preparing benchmark-specific input data.

    The behavior of this class, particularly the `build` method, depends on the
    state of the SeBS cache:
    1. If no cache entry exists for the benchmark (for the current language, deployment, etc.),
       a new code package is built.
    2. If a cache entry exists, the hash of the benchmark's source directory is computed
       and compared with the cached hash. If they differ, or if an update is forced,
       the package is rebuilt.
    3. Otherwise (cache entry exists and hash matches), the cached code package is used.
    """
    @staticmethod
    def typename() -> str:
        """Return the type name of this class."""
        return "Benchmark"

    @property
    def benchmark(self) -> str:
        """The name of the benchmark (e.g., "010.sleep")."""
        return self._benchmark

    @property
    def benchmark_path(self) -> str:
        """The absolute path to the benchmark's source directory."""
        return self._benchmark_path

    @property
    def benchmark_config(self) -> BenchmarkConfig:
        """The BenchmarkConfig object for this benchmark."""
        return self._benchmark_config

    @property
    def code_package(self) -> Optional[dict]: # Can be None if not cached/built
        """
        Cached information about the code package, if available.
        This typically includes 'location' (relative to cache_dir), 'hash', and 'size'.
        """
        return self._code_package

    @property
    def functions(self) -> Dict[str, Any]: # Value can be complex, from Function.deserialize
        """
        Cached information about deployed functions associated with this benchmark
        for the current deployment, keyed by function name.
        """
        return self._functions

    @property
    def code_location(self) -> str:
        """
        The absolute path to the prepared code package.
        If cached, it points to the location within the SeBS cache directory.
        Otherwise, it points to the build output directory.
        """
        if self._code_package and "location" in self._code_package:
            return os.path.join(self._cache_client.cache_dir, self._code_package["location"])
        else:
            # Before build or if not cached, this might point to the intended output dir
            # or could be considered unset. The _output_dir is set in __init__.
            return self._output_dir # Changed from self._code_location which was not set

    @property
    def is_cached(self) -> bool:
        """True if a code package entry for this benchmark exists in the cache."""
        return self._is_cached

    @is_cached.setter
    def is_cached(self, val: bool):
        """Set the cached status."""
        self._is_cached = val

    @property
    def is_cached_valid(self) -> bool:
        """
        True if a cached code package exists and its hash matches the current
        benchmark source code hash.
        """
        return self._is_cached_valid

    @is_cached_valid.setter
    def is_cached_valid(self, val: bool):
        """Set the cache validity status."""
        self._is_cached_valid = val

    @property
    def code_size(self) -> Optional[int]: # Can be None if not set
        """The size of the code package in bytes, if known."""
        return self._code_size

    @property
    def container_uri(self) -> Optional[str]: # Changed from str to Optional[str]
        """The URI of the container image, if applicable for containerized deployment."""
        return self._container_uri

    @property
    def language(self) -> "Language":
        """The programming language of this benchmark instance (Language enum)."""
        return self._language

    @property
    def language_name(self) -> str:
        """The string name of the programming language (e.g., "python")."""
        return self._language.value

    @property
    def language_version(self) -> str: # Added return type
        """The version of the programming language runtime (e.g., "3.8")."""
        return self._language_version

    @property
    def has_input_processed(self) -> bool:
        """True if the benchmark's input data has been prepared and processed."""
        return self._input_processed

    @property
    def uses_storage(self) -> bool:
        """True if the benchmark requires object storage (e.g., S3, Minio)."""
        return self._uses_storage

    @property
    def uses_nosql(self) -> bool:
        """True if the benchmark requires NoSQL storage (e.g., DynamoDB, ScyllaDB)."""
        return self._uses_nosql

    @property
    def architecture(self) -> str:
        """The target CPU architecture for this benchmark instance (e.g., "x64")."""
        return self._architecture

    @property
    def container_deployment(self) -> bool: # Added return type
        """True if this benchmark instance is intended for containerized deployment."""
        return self._container_deployment

    @property  # noqa: A003
    def hash(self) -> Optional[str]: # Can be None before first calculation
        """
        MD5 hash of the benchmark's source code directory for the current language
        and deployment, including relevant wrappers. Used for cache validation.
        """
        # Calculate hash on demand if not already computed
        if self._hash_value is None:
            path = os.path.join(self.benchmark_path, self.language_name)
            self._hash_value = Benchmark.hash_directory(path, self._deployment_name, self.language_name)
        return self._hash_value

    @hash.setter  # noqa: A003
    def hash(self, val: str):
        """
        Set the hash value. Used only for testing purposes.

        :param val: The hash value to set.
        """
        self._hash_value = val

    def __init__(
        self,
        benchmark: str,
        deployment_name: str,
        config: "ExperimentConfig", # Experiment-level config
        system_config: SeBSConfig, # Global SeBS config
        output_dir: str, # Base output directory for SeBS
        cache_client: Cache,
        docker_client: docker.client,
    ):
        """
        Initialize a Benchmark instance.

        Loads benchmark configuration, determines language and version from experiment
        config, sets up paths, and queries the cache for existing code packages
        and function deployments.

        :param benchmark: Name of the benchmark.
        :param deployment_name: Name of the target FaaS deployment (e.g., "aws", "local").
        :param config: The active experiment's configuration.
        :param system_config: The global SeBS system configuration.
        :param output_dir: Base directory for SeBS outputs.
        :param cache_client: The SeBS cache client.
        :param docker_client: The Docker client instance.
        :raises RuntimeError: If the benchmark is not found or not supported for the language.
        """
        super().__init__()
        self._benchmark = benchmark
        self._deployment_name = deployment_name
        self._experiment_config = config # Experiment-specific settings
        self._language = config.runtime.language
        self._language_version = config.runtime.version
        self._architecture = self._experiment_config.architecture
        self._container_deployment = config.container_deployment
        
        benchmark_fs_path = find_benchmark(self.benchmark, "benchmarks")
        if not benchmark_fs_path:
            raise RuntimeError(f"Benchmark {self.benchmark} not found!")
        self._benchmark_path = benchmark_fs_path
        
        with open(os.path.join(self.benchmark_path, "config.json")) as json_file:
            self._benchmark_config: BenchmarkConfig = BenchmarkConfig.deserialize(json.load(json_file))
        
        if self.language not in self.benchmark_config.languages:
            raise RuntimeError(f"Benchmark {self.benchmark} not available for language {self.language_name}")
        
        self._cache_client = cache_client
        self._docker_client = docker_client
        self._system_config = system_config # Global SeBS settings
        self._hash_value: Optional[str] = None # Lazily computed
        self._code_package: Optional[Dict[str, Any]] = None # From cache
        self._code_size: Optional[int] = None # From cache or after build
        self._functions: Dict[str, Any] = {} # From cache

        # Directory for this specific benchmark variant's build outputs
        self._output_dir = os.path.join(
            output_dir, # Base SeBS output directory
            f"{benchmark}_code",
            self._language.value,
            self._language_version,
            self._architecture,
            "container" if self._container_deployment else "package",
        )
        self._container_uri: Optional[str] = None
        self._code_location: str = self._output_dir # Default if not cached

        self.query_cache() # Populate _code_package, _functions, _is_cached, etc.
        if config.update_code: # If user forces code update
            self._is_cached_valid = False

        # Load input generation module for this benchmark
        benchmark_data_root = find_benchmark(self._benchmark, "benchmarks-data")
        if not benchmark_data_root:
             self.logging.warning(f"Data directory for benchmark {self._benchmark} not found.")
             # Decide if this is fatal or if benchmark can run without data_dir
        self._benchmark_data_path: Optional[str] = benchmark_data_root
        self._benchmark_input_module: BenchmarkModuleInterface = load_benchmark_input(self._benchmark_path)

        self._input_processed: bool = False
        self._uses_storage: bool = False # Determined during input preparation
        self._uses_nosql: bool = False   # Determined during input preparation

    @staticmethod
    def hash_directory(directory: str, deployment: str, language_name: str) -> str: # language -> language_name
        """
        Compute an MD5 hash of a directory's contents relevant to a benchmark.

        Includes source files (*.py, requirements.txt for Python; *.js, package.json for Node.js),
        non-language-specific files (*.sh, *.json), and deployment-specific wrapper files.

        :param directory: The path to the benchmark's language-specific source directory.
        :param deployment: The name of the target deployment (e.g., "aws").
        :param language_name: The name of the programming language ("python" or "nodejs").
        :return: MD5 hexdigest string of the relevant directory contents.
        """
        hash_sum = hashlib.md5()
        FILES_PATTERNS = { # Renamed from FILES for clarity
            "python": ["*.py", "requirements.txt*"], # requirements.txt* for versioned ones
            "nodejs": ["*.js", "package.json"],
        }
        WRAPPER_PATTERNS = {"python": "*.py", "nodejs": "*.js"} # Renamed from WRAPPERS
        COMMON_FILES_PATTERNS = ["*.sh", "*.json"] # Renamed from NON_LANG_FILES

        selected_patterns = FILES_PATTERNS[language_name] + COMMON_FILES_PATTERNS
        for pattern in selected_patterns:
            for filepath in glob.glob(os.path.join(directory, pattern)):
                if os.path.isfile(filepath): # Ensure it's a file
                    with open(filepath, "rb") as f_obj:
                        hash_sum.update(f_obj.read())
        
        # Include wrappers
        wrapper_search_path = project_absolute_path(
            "benchmarks", "wrappers", deployment, language_name, WRAPPER_PATTERNS[language_name]
        )
        for filepath in glob.glob(wrapper_search_path):
             if os.path.isfile(filepath):
                with open(filepath, "rb") as f_obj:
                    hash_sum.update(f_obj.read())
        return hash_sum.hexdigest()

    def serialize(self) -> dict:
        """
        Serialize essential benchmark information (size and hash) for caching.

        :return: Dictionary with "size" and "hash".
        """
        return {"size": self.code_size, "hash": self.hash}

    def query_cache(self):
        """
        Query the SeBS cache for existing code packages and function deployments
        for this benchmark variant. Updates internal state based on cache findings
        (e.g., `_is_cached`, `_is_cached_valid`, `_code_package`, `_functions`).
        """
        if self.container_deployment:
            self._code_package = self._cache_client.get_container(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.language_name,
                language_version=self.language_version,
                architecture=self.architecture,
            )
            if self._code_package is not None:
                self._container_uri = self._code_package.get("image-uri") # Use .get for safety
        else:
            self._code_package = self._cache_client.get_code_package(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.language_name,
                language_version=self.language_version,
                architecture=self.architecture,
            )

        self._functions = self._cache_client.get_functions(
            deployment=self._deployment_name,
            benchmark=self._benchmark,
            language=self.language_name, # Assumes functions are per language, not version specific in cache key
        )

        if self._code_package is not None:
            current_hash = self.hash # Ensures hash is computed if not already
            old_hash = self._code_package.get("hash")
            self._code_size = self._code_package.get("size")
            self._is_cached = True
            self._is_cached_valid = (current_hash == old_hash) if old_hash else False
            if self._is_cached_valid:
                 self._code_location = os.path.join(self._cache_client.cache_dir, self._code_package["location"])
        else:
            self._is_cached = False
            self._is_cached_valid = False
            self._code_location = self._output_dir # Default to build output if not cached

    def copy_code(self, output_dir: str):
        """
        Copy benchmark source files (language-specific and common) to the output directory.

        Handles language-specific files (e.g., *.py, requirements.txt for Python)
        and versioned package.json for Node.js.

        :param output_dir: The target directory for copying files.
        """
        FILES_PATTERNS = {
            "python": ["*.py", "requirements.txt*"],
            "nodejs": ["*.js", "package.json"],
        }
        source_path = os.path.join(self.benchmark_path, self.language_name)
        for pattern in FILES_PATTERNS[self.language_name]:
            for filepath in glob.glob(os.path.join(source_path, pattern)):
                if os.path.isfile(filepath):
                    shutil.copy2(filepath, output_dir)
        
        # Support Node.js benchmarks with language version-specific package.json
        if self.language_name == "nodejs":
            versioned_package_json = os.path.join(source_path, f"package.json.{self.language_version}")
            if os.path.exists(versioned_package_json):
                shutil.copy2(versioned_package_json, os.path.join(output_dir, "package.json"))

    def add_benchmark_data(self, output_dir: str):
        """
        Add benchmark-specific data files by running `init.sh` script if it exists.

        Searches for `init.sh` in the benchmark's root and language-specific directories.
        The script is executed with the output directory and architecture as arguments.

        :param output_dir: The target directory where data should be placed or referenced.
        """
        # The script is expected to handle placing data correctly relative to output_dir
        init_script_cmd = "/bin/bash {script_path} {target_dir} false {arch}"
        # Check in benchmark root, then language-specific subdir
        possible_script_locations = [
            os.path.join(self.benchmark_path, "init.sh"),
            os.path.join(self.benchmark_path, self.language_name, "init.sh"),
        ]
        for script_path in possible_script_locations:
            if os.path.exists(script_path):
                self.logging.info(f"Executing benchmark data script: {script_path}")
                subprocess.run(
                    init_script_cmd.format(
                        script_path=script_path,
                        target_dir=output_dir,
                        arch=self._experiment_config.architecture, # Use architecture from experiment config
                    ),
                    shell=True, # Be cautious with shell=True
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False # Check return code manually if needed
                )
                break # Assume only one init.sh should be run

    def add_deployment_files(self, output_dir: str):
        """
        Copy deployment-specific wrapper files (e.g., handlers) to the output directory.

        Files are sourced from `benchmarks/wrappers/{deployment_name}/{language_name}/`.

        :param output_dir: The target directory for copying wrapper files.
        """
        handlers_source_dir = project_absolute_path(
            "benchmarks", "wrappers", self._deployment_name, self.language_name
        )
        # Get list of file names, not full paths, from system_config
        required_handler_files = self._system_config.deployment_files(
            self._deployment_name, self.language_name
        )
        for file_name in required_handler_files:
            source_file_path = os.path.join(handlers_source_dir, file_name)
            if os.path.exists(source_file_path):
                shutil.copy2(source_file_path, os.path.join(output_dir, file_name))
            else:
                self.logging.warning(f"Deployment wrapper file {source_file_path} not found.")


    def add_deployment_package_python(self, output_dir: str):
        """
        Add deployment-specific Python packages to the requirements.txt file.

        Appends packages listed in SeBS system configuration for the current
        deployment, language, and any required benchmark modules.
        Handles versioned requirements files (e.g., requirements.txt.3.8).

        :param output_dir: The directory containing the requirements.txt file.
        """
        # Determine the correct requirements file (e.g., requirements.txt.3.8 or requirements.txt)
        versioned_req_file = f"requirements.txt.{self._language_version}"
        req_file_path = os.path.join(output_dir, versioned_req_file)
        if not os.path.exists(req_file_path):
            req_file_path = os.path.join(output_dir, "requirements.txt")
            if not os.path.exists(req_file_path): # Create if doesn't exist
                 with open(req_file_path, "w") as f:
                     pass # Create empty file
                 self.logging.info(f"Created empty requirements file at {req_file_path}")


        with open(req_file_path, "a") as out_f: # Open in append mode
            # Add general deployment packages
            general_packages = self._system_config.deployment_packages(
                self._deployment_name, self.language_name
            )
            for package in general_packages:
                out_f.write(f"{package}\n") # Ensure newline

            # Add packages for specific benchmark modules
            module_specific_packages = self._system_config.deployment_module_packages(
                self._deployment_name, self.language_name
            )
            for bench_module in self._benchmark_config.modules:
                if bench_module.value in module_specific_packages:
                    for package in module_specific_packages[bench_module.value]:
                        out_f.write(f"{package}\n") # Ensure newline

    def add_deployment_package_nodejs(self, output_dir: str):
        """
        Add deployment-specific Node.js packages to the package.json file.

        Merges dependencies from SeBS system configuration into the benchmark's
        package.json. Handles versioned package.json files (e.g., package.json.12).

        :param output_dir: The directory containing the package.json file.
        """
        # Determine the correct package.json file
        versioned_pkg_file = f"package.json.{self._language_version}"
        pkg_file_path = os.path.join(output_dir, versioned_pkg_file)
        if not os.path.exists(pkg_file_path):
            pkg_file_path = os.path.join(output_dir, "package.json")
            if not os.path.exists(pkg_file_path):
                # Create a default package.json if none exists
                default_pkg_json = {"name": self.benchmark, "version": "1.0.0", "dependencies": {}}
                with open(pkg_file_path, "w") as f:
                    json.dump(default_pkg_json, f, indent=2)
                self.logging.info(f"Created default package.json at {pkg_file_path}")


        # Read existing package.json
        with open(pkg_file_path, "r") as package_file:
            package_json_data = json.load(package_file)
        
        # Ensure 'dependencies' key exists
        if "dependencies" not in package_json_data:
            package_json_data["dependencies"] = {}
            
        # Add general deployment packages
        general_packages = self._system_config.deployment_packages(
            self._deployment_name, self.language_name
        )
        package_json_data["dependencies"].update(general_packages) # Merge dependencies

        # Add packages for specific benchmark modules
        # This part was missing in original, adding for completeness if modules can have npm deps
        module_specific_packages = self._system_config.deployment_module_packages(
             self._deployment_name, self.language_name
        )
        for bench_module in self._benchmark_config.modules:
            if bench_module.value in module_specific_packages:
                 package_json_data["dependencies"].update(module_specific_packages[bench_module.value])


        # Write updated package.json
        with open(pkg_file_path, "w") as package_file:
            json.dump(package_json_data, package_file, indent=2)

    def add_deployment_package(self, output_dir: str):
        """
        Add deployment-specific packages based on the benchmark's language.

        Dispatches to language-specific methods (Python, Node.js).

        :param output_dir: The directory where package files (e.g., requirements.txt) are located.
        :raises NotImplementedError: If the language is not supported.
        """
        from sebs.faas.function import Language # Local import

        if self.language == Language.PYTHON:
            self.add_deployment_package_python(output_dir)
        elif self.language == Language.NODEJS:
            self.add_deployment_package_nodejs(output_dir)
        else:
            raise NotImplementedError(f"Deployment package addition not implemented for language {self.language_name}")

    @staticmethod
    def directory_size(directory: str) -> int: # Return type is int (bytes)
        """
        Calculate the total size of all files within a directory (recursive).

        :param directory: The path to the directory.
        :return: Total size in bytes.
        """
        from pathlib import Path
        root = Path(directory)
        return sum(f.stat().st_size for f in root.glob("**/*") if f.is_file())

    def install_dependencies(self, output_dir: str):
        """
        Install benchmark dependencies using a Docker container.

        Pulls a pre-built Docker image specific to the deployment, language, and
        runtime version. Mounts the output directory into the container and runs
        an installer script (`/sebs/installer.sh`) within the container.
        Handles fallbacks to unversioned Docker images if versioned ones are not found.
        Supports copying files to/from Docker for environments where volume mounting
        is problematic (e.g., CircleCI).

        :param output_dir: The directory containing benchmark code and dependency files.
                           Dependencies will be installed into this directory (or subdirectories
                           like .python_packages or node_modules).
        :raises RuntimeError: If Docker image pull fails or container execution fails.
        """
        # Check if a Docker build image is defined for this deployment and language
        if "build" not in self._system_config.docker_image_types(
            self._deployment_name, self.language_name
        ):
            self.logging.info(
                f"No Docker build image for {self._deployment_name} in {self.language_name}, "
                "skipping Docker-based dependency installation."
            )
            return # Skip if no build image is configured

        repo_name = self._system_config.docker_repository()
        # Construct image names (versioned and unversioned fallback)
        unversioned_image_name = f"build.{self._deployment_name}.{self.language_name}.{self.language_version}"
        versioned_image_name = f"{unversioned_image_name}-{self._system_config.version()}"
        
        final_image_name_to_use = versioned_image_name

        def _ensure_docker_image(image_name_with_tag: str) -> bool:
            try:
                self._docker_client.images.get(f"{repo_name}:{image_name_with_tag}")
                return True
            except docker.errors.ImageNotFound:
                try:
                    self.logging.info(f"Pulling Docker image {repo_name}:{image_name_with_tag}")
                    self._docker_client.images.pull(repo_name, image_name_with_tag)
                    return True
                except docker.errors.APIError as e_pull:
                    self.logging.warning(f"Docker pull of {repo_name}:{image_name_with_tag} failed: {e_pull}")
                    return False
        
        if not _ensure_docker_image(versioned_image_name):
            self.logging.warning(
                f"Failed to ensure image {versioned_image_name}, falling back to {unversioned_image_name}."
            )
            if not _ensure_docker_image(unversioned_image_name):
                raise RuntimeError(f"Failed to pull both versioned and unversioned Docker build images.")
            final_image_name_to_use = unversioned_image_name
        
        # Prepare for Docker run
        volumes = {}
        if not self._experiment_config.check_flag("docker_copy_build_files"):
            volumes[os.path.abspath(output_dir)] = {"bind": "/mnt/function", "mode": "rw"}
            package_script_path = os.path.abspath(
                os.path.join(self._benchmark_path, self.language_name, "package.sh")
            )
            if os.path.exists(package_script_path):
                volumes[package_script_path] = {"bind": "/mnt/function/package.sh", "mode": "ro"}
        
        # Check if primary dependency file exists (e.g. requirements.txt)
        PACKAGE_MANIFEST_FILES = {"python": "requirements.txt", "nodejs": "package.json"}
        dependency_file_path = os.path.join(output_dir, PACKAGE_MANIFEST_FILES[self.language_name])
        if not os.path.exists(dependency_file_path):
            self.logging.info(f"No dependency file ({dependency_file_path}) found. Skipping dependency installation.")
            return

        try:
            self.logging.info(
                f"Starting Docker-based dependency installation using image {repo_name}:{final_image_name_to_use}"
            )
            container_user_id = str(os.getuid()) if hasattr(os, 'getuid') else '1000'
            container_group_id = str(os.getgid()) if hasattr(os, 'getgid') else '1000'

            if not self._experiment_config.check_flag("docker_copy_build_files"):
                self.logging.info(f"Using Docker volume mount for {os.path.abspath(output_dir)}")
                run_stdout = self._docker_client.containers.run(
                    f"{repo_name}:{final_image_name_to_use}",
                    volumes=volumes,
                    environment={
                        "CONTAINER_UID": container_user_id,
                        "CONTAINER_GID": container_group_id,
                        "CONTAINER_USER": "docker_user", # User inside container
                        "APP": self.benchmark,
                        "PLATFORM": self._deployment_name.upper(),
                        "TARGET_ARCHITECTURE": self._experiment_config.architecture,
                    },
                    remove=True, stdout=True, stderr=True,
                )
                stdout_decoded = run_stdout.decode("utf-8")
            else: # Fallback for environments where mounts are problematic (e.g., CI)
                self.logging.info("Using Docker cp for file transfer due to 'docker_copy_build_files' flag.")
                container = self._docker_client.containers.run(
                    f"{repo_name}:{final_image_name_to_use}",
                    environment={"APP": self.benchmark, 
                                 "TARGET_ARCHITECTURE": self._experiment_config.architecture},
                    user=container_user_id, # Run as current host user if possible
                    remove=True, detach=True, tty=True, command="/bin/bash", # Keep alive
                )
                # Copy files to container
                tar_archive_path = os.path.join(os.path.dirname(output_dir), "function_package.tar")
                with tarfile.open(tar_archive_path, "w") as tar:
                    tar.add(output_dir, arcname=".") # Add contents of output_dir to root of tar
                with open(tar_archive_path, "rb") as tar_data:
                    container.put_archive("/mnt/function", tar_data)
                os.remove(tar_archive_path) # Clean up tar

                # Execute installer script
                exec_result = container.exec_run(
                    cmd="/bin/bash /sebs/installer.sh", user="docker_user", # Run installer as docker_user
                    stdout=True, stderr=True
                )
                stdout_decoded = exec_result.output.decode("utf-8")
                if exec_result.exit_code != 0:
                     self.logging.error(f"Dependency installation script failed with exit code {exec_result.exit_code}")
                     self.logging.error(f"Stderr: {stdout_decoded}") # Stderr is part of output here
                     raise docker.errors.ContainerError(container, exec_result.exit_code, cmd, final_image_name_to_use, stdout_decoded)


                # Copy results back
                # Need to clean output_dir before extracting to avoid issues with old files
                # For simplicity, assume installer script places files correctly in /mnt/function
                # and we are extracting the entire /mnt/function back.
                # This might overwrite source files if installer modifies them, which is usually not intended.
                # A safer approach might be to copy only specific dependency dirs (e.g. .python_packages)
                data_stream, _ = container.get_archive("/mnt/function")
                with open(tar_archive_path, "wb") as f_tar_out:
                    for chunk in data_stream:
                        f_tar_out.write(chunk)
                
                # Before extracting, ensure output_dir is clean of old dependency dirs
                # Example: shutil.rmtree(os.path.join(output_dir, ".python_packages"), ignore_errors=True)
                with tarfile.open(tar_archive_path, "r") as tar_in:
                    tar_in.extractall(output_dir) # Extracts to output_dir
                os.remove(tar_archive_path)
                container.stop()

            for line in stdout_decoded.split("\n"):
                if "size" in line: # Log any size information from installer
                    self.logging.info(f"Docker build output: {line}")
        
        except docker.errors.ContainerError as e:
            self.logging.error(f"Dependency installation in Docker failed: {e}")
            if hasattr(e, 'stderr') and e.stderr:
                self.logging.error(f"Container stderr: {e.stderr.decode('utf-8')}")
            raise


    def recalculate_code_size(self) -> int: # Return type is int (bytes)
        """
        Recalculate the size of the code package directory and update `_code_size`.

        :return: The recalculated code size in bytes.
        """
        self._code_size = Benchmark.directory_size(self._output_dir)
        return self._code_size

    def build(
        self,
        deployment_build_step: Callable[
            [str, str, str, str, str, bool, bool], Tuple[str, int, str]
        ],
    ) -> Tuple[bool, str, bool, str]:
        """
        Build the benchmark code package.

        This involves copying source code, adding benchmark data and deployment-specific
        files, installing dependencies, and then running the FaaS provider's specific
        packaging step (e.g., zipping, creating container image).
        Updates the cache with the new package information.

        :param deployment_build_step: A callable provided by the FaaS system implementation
                                      that performs the final packaging (e.g., zipping, image build).
                                      Signature: (abs_output_dir, lang_name, lang_version, arch,
                                                  benchmark_name, is_cached_valid, is_container_deployment)
                                      Returns: (package_path, package_size_bytes, container_uri_if_any)
        :return: Tuple (rebuilt: bool, code_location: str, is_container: bool, container_uri: str).
                 `rebuilt` is True if the package was newly built/rebuilt.
        """
        # Skip build if files are up-to-date and user didn't enforce rebuild
        if self.is_cached and self.is_cached_valid:
            self.logging.info(
                f"Using cached benchmark {self.benchmark} at {self.code_location}"
            )
            # Ensure container_uri is correctly set from cache if it's a container deployment
            container_uri_to_return = self.container_uri if self.container_deployment else ""
            return False, self.code_location, self.container_deployment, container_uri_to_return or ""


        reason_for_build = ("no cached code package." if not self.is_cached
                            else "cached code package is not up-to-date or build enforced.")
        self.logging.info(f"Building benchmark {self.benchmark}. Reason: {reason_for_build}")
        self._code_package = None # Clear existing cache info as we are rebuilding

        # Create or clear the output directory for this build
        if os.path.exists(self._output_dir):
            shutil.rmtree(self._output_dir)
        os.makedirs(self._output_dir)

        # Assemble benchmark code and dependencies
        self.copy_code(self._output_dir)
        if self._benchmark_data_path: # Only if data path exists
            self.add_benchmark_data(self._output_dir)
        self.add_deployment_files(self._output_dir)
        self.add_deployment_package(self._output_dir)
        self.install_dependencies(self._output_dir) # Installs into _output_dir

        # Perform deployment-specific packaging (e.g., zip, build image)
        # deployment_build_step is responsible for the final package/image.
        # It operates on the contents of self._output_dir.
        package_path, package_size, container_image_uri = deployment_build_step(
            os.path.abspath(self._output_dir), # Pass absolute path to build step
            self.language_name,
            self.language_version,
            self.architecture,
            self.benchmark,
            self.is_cached_valid, # Pass current validity, though it's being rebuilt
            self.container_deployment,
        )
        
        self._code_location = package_path # This is the final packaged code location
        self._code_size = package_size
        self._container_uri = container_image_uri if self.container_deployment else None

        self.logging.info(
            f"Created code package (source hash: {self.hash}), for run on {self._deployment_name} "
            f"with {self.language_name}:{self.language_version}"
        )

        # Update cache with the new package information
        if self.container_deployment:
            self._cache_client.add_container(self._deployment_name, self)
        else:
            if self.is_cached: # If there was an old entry, update it
                self._cache_client.update_code_package(self._deployment_name, self)
            else: # Otherwise, add a new entry
                self._cache_client.add_code_package(self._deployment_name, self)
        
        self.query_cache() # Refresh internal state from cache

        return True, self._code_location, self.container_deployment, self._container_uri or ""


    def prepare_input(
        self, system_resources: SystemResources, size: str, replace_existing: bool = False
    ) -> Dict[str, Any]: # Return type changed to Dict[str, Any]
        """
        Prepare input data for the benchmark.

        Locates the benchmark's input generator module (`input.py`), determines
        storage requirements (object storage buckets, NoSQL tables), and invokes
        the `generate_input` function from the module to create and upload
        input data. Updates the cache with storage details after successful preparation.

        :param system_resources: The SystemResources instance for the current deployment.
        :param size: Workload size identifier (e.g., "test", "small", "large").
        :param replace_existing: If True, overwrite existing input data in storage.
        :return: A dictionary containing the input configuration for the benchmark invocation.
        """
        input_config_dict: Dict[str, Any] = {}
        storage_func: Optional[Callable[[int, str, str], None]] = None
        target_bucket_for_input: Optional[str] = None
        input_prefixes_list: List[str] = []
        output_prefixes_list: List[str] = []

        # Handle object storage buckets
        if hasattr(self._benchmark_input_module, "buckets_count"):
            num_input_buckets, num_output_buckets = self._benchmark_input_module.buckets_count()
            if num_input_buckets > 0 or num_output_buckets > 0:
                storage_client = system_resources.get_storage(replace_existing)
                input_prefixes_list, output_prefixes_list = storage_client.benchmark_data(
                    self.benchmark, (num_input_buckets, num_output_buckets)
                )
                self._uses_storage = True
                storage_func = storage_client.uploader_func
                target_bucket_for_input = storage_client.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        
        # Handle NoSQL storage
        nosql_func: Optional[Callable] = None # Define with broader scope
        if hasattr(self._benchmark_input_module, "allocate_nosql"):
            nosql_storage_client = system_resources.get_nosql_storage()
            tables_to_allocate = self._benchmark_input_module.allocate_nosql()
            if tables_to_allocate: # Only proceed if there are tables defined
                for table_name, table_props in tables_to_allocate.items():
                    nosql_storage_client.create_benchmark_tables(
                        self._benchmark,
                        table_name,
                        table_props["primary_key"],
                        table_props.get("secondary_key"),
                    )
                self._uses_nosql = True
                nosql_func = nosql_storage_client.write_to_table
        
        # Generate input using the benchmark's specific input.py module
        if self._benchmark_data_path: # Ensure data path is valid
            input_config_dict = self._benchmark_input_module.generate_input(
                self._benchmark_data_path, size, target_bucket_for_input,
                input_prefixes_list, output_prefixes_list,
                storage_func, nosql_func
            )
        else:
            self.logging.warning(f"Benchmark data path for {self.benchmark} is not set, cannot generate input.")
            # Return empty or default config if data path is missing
            input_config_dict = {"default_input": True, "size": size}


        # Update cache after successful data upload/preparation
        if self._uses_storage and hasattr(self._benchmark_input_module, "buckets_count"):
            # Assuming storage_client is the one from above
            storage_client = system_resources.get_storage()
            self._cache_client.update_storage(
                storage_client.deployment_name(),
                self._benchmark,
                {
                    "buckets": {
                        "input": storage_client.input_prefixes,
                        "output": storage_client.output_prefixes,
                        "input_uploaded": True, # Mark as uploaded
                    }
                },
            )
        if self._uses_nosql and hasattr(self._benchmark_input_module, "allocate_nosql"):
            nosql_storage_client = system_resources.get_nosql_storage()
            nosql_storage_client.update_cache(self._benchmark)

        self._input_processed = True
        return input_config_dict


    def code_package_modify(self, filename: str, data: bytes):
        """
        Modify a file within the benchmark's code package.

        This is used in experiments that vary code package contents (e.g., size).
        Currently only supports modification if the code package is a zip archive.

        :param filename: The name of the file within the package to modify/add.
        :param data: The new byte content for the file.
        :raises NotImplementedError: If the code package is not a zip archive.
        """
        if self.code_package_is_archive():
            self._update_zip(self.code_location, filename, data)
            new_size_bytes = self.code_package_recompute_size() # Returns float, but should be int
            new_size_mb = new_size_bytes / 1024.0 / 1024.0
            self.logging.info(f"Modified zip package {self.code_location}, new size {new_size_mb:.2f} MB")
        else:
            # This could be extended to handle modifications to directories for non-archive deployments
            raise NotImplementedError("Code package modification is currently only supported for zip archives.")


    def code_package_is_archive(self) -> bool:
        """
        Check if the benchmark's code package is an archive file (specifically, a .zip file).

        :return: True if the code package is a .zip file, False otherwise.
        """
        # Ensure code_location is valid and points to a file
        loc = self.code_location
        if loc and os.path.isfile(loc):
            _, extension = os.path.splitext(loc)
            return extension.lower() == ".zip"
        return False

    def code_package_recompute_size(self) -> int: # Changed return to int
        """
        Recompute the size of the code package file and update `_code_size`.

        :return: The recomputed code package size in bytes.
        """
        bytes_size = 0
        if self.code_location and os.path.exists(self.code_location): # Check existence
            bytes_size = os.path.getsize(self.code_location)
        self._code_size = bytes_size
        return bytes_size

    @staticmethod
    def _update_zip(zip_archive_path: str, filename_in_zip: str, data_bytes: bytes): # Renamed args
        """
        Update a file within an existing zip archive, or add it if not present.

        Creates a temporary zip file, copies all items from the original except
        the target file (if it exists), then adds/replaces the target file with
        new data. Finally, replaces the original zip with the temporary one.
        Based on method from: https://stackoverflow.com/questions/25738523/how-to-update-one-file-inside-zip-file-using-python

        :param zip_archive_path: Path to the zip archive to update.
        :param filename_in_zip: The internal path/name of the file within the zip archive.
        :param data_bytes: The new byte content for the file.
        """
        import zipfile
        import tempfile

        temp_fd, temp_zip_path = tempfile.mkstemp(dir=os.path.dirname(zip_archive_path), suffix='.zip')
        os.close(temp_fd)

        try:
            with zipfile.ZipFile(zip_archive_path, "r") as original_zip:
                with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as temp_new_zip:
                    temp_new_zip.comment = original_zip.comment # Preserve comment
                    for item in original_zip.infolist():
                        if item.filename != filename_in_zip:
                            temp_new_zip.writestr(item, original_zip.read(item.filename))
                    # Add the new/updated file
                    temp_new_zip.writestr(filename_in_zip, data_bytes)
            
            # Replace original with the new zip
            os.remove(zip_archive_path)
            os.rename(temp_zip_path, zip_archive_path)
        except Exception:
            # Ensure temp file is removed on error before re-raising
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            raise


class BenchmarkModuleInterface:
    """
    Defines the expected interface for a benchmark's `input.py` module.

    This class is used for static type hinting and documentation purposes.
    Benchmark input modules should provide static methods matching this interface.
    """
    @staticmethod
    @abstractmethod
    def buckets_count() -> Tuple[int, int]:
        """
        Return the number of input and output storage buckets required by the benchmark.

        :return: Tuple (number_of_input_buckets, number_of_output_buckets).
        """
        pass

    @staticmethod
    @abstractmethod
    def allocate_nosql() -> dict:
        """
        Return a dictionary specifying NoSQL tables to be allocated for the benchmark.
        The dictionary format is: { "table_alias_1": {"primary_key": "key_name", "secondary_key": "sort_key_name"}, ... }
        'secondary_key' is optional.

        :return: Dictionary describing NoSQL table requirements.
        """
        pass

    @staticmethod
    @abstractmethod
    def generate_input(
        data_dir: Optional[str], # data_dir can be None if benchmark doesn't need external data files
        size: str,
        benchmarks_bucket: Optional[str], # Name of the main benchmark data bucket
        input_paths: List[str], # List of input prefixes/paths within the bucket
        output_paths: List[str], # List of output prefixes/paths within the bucket
        # Type for upload_func: (prefix_idx: int, key_in_prefix: str, local_filepath: str) -> None
        upload_func: Optional[Callable[[int, str, str], None]],
        # Type for nosql_func: (benchmark_name: str, table_alias: str, data_item: dict,
        #                        pk_tuple: Tuple[str,str], sk_tuple: Optional[Tuple[str,str]]) -> None
        nosql_func: Optional[
            Callable[[str, str, dict, Tuple[str, str], Optional[Tuple[str, str]]], None]
        ],
    ) -> Dict[str, Any]: # Return type changed to Dict[str, Any] for flexibility
        """
        Generate and upload benchmark input data, and prepare the input configuration.

        :param data_dir: Path to the directory containing benchmark-specific data files.
        :param size: Workload size identifier (e.g., "test", "small").
        :param benchmarks_bucket: Name of the primary bucket for benchmark data.
        :param input_paths: List of input prefixes/paths within the `benchmarks_bucket`.
        :param output_paths: List of output prefixes/paths within the `benchmarks_bucket`.
        :param upload_func: Optional callback function to upload files to object storage.
                            Signature: `upload_func(prefix_index, key_relative_to_prefix, local_file_path)`
        :param nosql_func: Optional callback function to write items to NoSQL storage.
                           Signature: `nosql_func(benchmark_name, table_alias, item_data, pk_tuple, sk_tuple)`
        :return: Dictionary containing the input configuration for the function invocation.
        """
        pass


def load_benchmark_input(benchmark_path: str) -> BenchmarkModuleInterface:
    """
    Load a benchmark's input generation module (`input.py`) dynamically.

    The `input.py` file is expected to be in the root of the benchmark's
    source directory (alongside its language-specific subdirectories).

    :param benchmark_path: Absolute path to the benchmark's root directory.
    :return: The loaded module, typed as BenchmarkModuleInterface.
    :raises ImportError: If the input.py module cannot be loaded.
    """
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("input", os.path.join(benchmark_path, "input.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod  # type: ignore

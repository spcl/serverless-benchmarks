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


class BenchmarkConfig:
    def __init__(
        self, timeout: int, memory: int, languages: List["Language"], modules: List[BenchmarkModule]
    ):
        self._timeout = timeout
        self._memory = memory
        self._languages = languages
        self._modules = modules

    @property
    def timeout(self) -> int:
        return self._timeout

    @timeout.setter
    def timeout(self, val: int):
        self._timeout = val

    @property
    def memory(self) -> int:
        return self._memory

    @memory.setter
    def memory(self, val: int):
        self._memory = val

    @property
    def languages(self) -> List["Language"]:
        return self._languages

    @property
    def modules(self) -> List[BenchmarkModule]:
        return self._modules

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(json_object: dict) -> "BenchmarkConfig":
        from sebs.faas.function import Language

        return BenchmarkConfig(
            json_object["timeout"],
            json_object["memory"],
            [Language.deserialize(x) for x in json_object["languages"]],
            [BenchmarkModule(x) for x in json_object["modules"]],
        )


"""
    Creates code package representing a benchmark with all code and assets
    prepared and dependency install performed within Docker image corresponding
    to the cloud deployment.

    The behavior of the class depends on cache state:
    1)  First, if there's no cache entry, a code package is built.
    2)  Otherwise, the hash of the entire benchmark is computed and compared
        with the cached value. If changed, then rebuilt then benchmark.
    3)  Otherwise, just return the path to cache code.
"""


class Benchmark(LoggingBase):
    @staticmethod
    def typename() -> str:
        return "Benchmark"

    @property
    def benchmark(self):
        return self._benchmark

    @property
    def benchmark_path(self):
        return self._benchmark_path

    @property
    def benchmark_config(self) -> BenchmarkConfig:
        return self._benchmark_config

    @property
    def code_package(self) -> dict:
        return self._code_package

    @property
    def functions(self) -> Dict[str, Any]:
        return self._functions

    @property
    def code_location(self):
        if self.code_package:
            return os.path.join(self._cache_client.cache_dir, self.code_package["location"])
        else:
            return self._code_location

    @property
    def is_cached(self):
        return self._is_cached

    @is_cached.setter
    def is_cached(self, val: bool):
        self._is_cached = val

    @property
    def is_cached_valid(self):
        return self._is_cached_valid

    @is_cached_valid.setter
    def is_cached_valid(self, val: bool):
        self._is_cached_valid = val

    @property
    def code_size(self):
        return self._code_size

    @property
    def container_uri(self) -> str:
        assert self._container_uri is not None
        return self._container_uri

    @property
    def language(self) -> "Language":
        return self._language

    @property
    def language_name(self) -> str:
        return self._language.value

    @property
    def language_version(self):
        return self._language_version

    @property
    def has_input_processed(self) -> bool:
        return self._input_processed

    @property
    def uses_storage(self) -> bool:
        return self._uses_storage

    @property
    def uses_nosql(self) -> bool:
        return self._uses_nosql

    @property
    def architecture(self) -> str:
        return self._architecture

    @property
    def container_deployment(self):
        return self._container_deployment

    @property  # noqa: A003
    def hash(self):
        path = os.path.join(self.benchmark_path, self.language_name)
        self._hash_value = Benchmark.hash_directory(path, self._deployment_name, self.language_name)
        return self._hash_value

    @hash.setter  # noqa: A003
    def hash(self, val: str):
        """
        Used only for testing purposes.
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
        docker_client: docker.client,
    ):
        super().__init__()
        self._benchmark = benchmark
        self._deployment_name = deployment_name
        self._experiment_config = config
        self._language = config.runtime.language
        self._language_version = config.runtime.version
        self._architecture = self._experiment_config.architecture
        self._container_deployment = config.container_deployment
        self._benchmark_path = find_benchmark(self.benchmark, "benchmarks")
        if not self._benchmark_path:
            raise RuntimeError("Benchmark {benchmark} not found!".format(benchmark=self._benchmark))
        with open(os.path.join(self.benchmark_path, "config.json")) as json_file:
            self._benchmark_config: BenchmarkConfig = BenchmarkConfig.deserialize(
                json.load(json_file)
            )
        if self.language not in self.benchmark_config.languages:
            raise RuntimeError(
                "Benchmark {} not available for language {}".format(self.benchmark, self.language)
            )
        self._cache_client = cache_client
        self._docker_client = docker_client
        self._system_config = system_config
        self._hash_value = None
        self._output_dir = os.path.join(
            output_dir,
            f"{benchmark}_code",
            self._language.value,
            self._language_version,
            self._architecture,
            "container" if self._container_deployment else "package",
        )
        self._container_uri: Optional[str] = None

        # verify existence of function in cache
        self.query_cache()
        if config.update_code:
            self._is_cached_valid = False

        # Load input module

        self._benchmark_data_path = find_benchmark(self._benchmark, "benchmarks-data")
        self._benchmark_input_module = load_benchmark_input(self._benchmark_path)

        # Check if input has been processed
        self._input_processed: bool = False
        self._uses_storage: bool = False
        self._uses_nosql: bool = False

    """
        Compute MD5 hash of an entire directory.
    """

    @staticmethod
    def hash_directory(directory: str, deployment: str, language: str):

        hash_sum = hashlib.md5()
        FILES = {
            "python": ["*.py", "requirements.txt*"],
            "nodejs": ["*.js", "package.json"],
            "rust": ["*.rs", "Cargo.toml", "Cargo.lock"],
            "java": ["src", "pom.xml"],
            "pypy": ["*.py", "requirements.txt*"],
        }
        WRAPPERS = {
            "python": ["*.py"],
            "nodejs": ["*.js"],
            "rust": None,
            "java": ["src", "pom.xml"],
            "pypy": ["*.py"],
        }
        NON_LANG_FILES = ["*.sh", "*.json"]
        selected_files = FILES[language] + NON_LANG_FILES
        for file_type in selected_files:
            for f in glob.glob(os.path.join(directory, file_type)):
                path = os.path.join(directory, f)
                if os.path.isdir(path):
                    for root, _, files in os.walk(path):
                        for file in sorted(files):
                            file_path = os.path.join(root, file)
                            with open(file_path, "rb") as opened_file:
                                hash_sum.update(opened_file.read())
                else:
                    with open(path, "rb") as opened_file:
                        hash_sum.update(opened_file.read())
        # For rust, also hash the src directory recursively
        if language == "rust":
            src_dir = os.path.join(directory, "src")
            if os.path.exists(src_dir):
                for root, dirs, files in os.walk(src_dir):
                    for file in sorted(files):
                        if file.endswith('.rs'):
                            path = os.path.join(root, file)
                            with open(path, "rb") as opened_file:
                                hash_sum.update(opened_file.read())
        # wrappers (Rust doesn't use wrapper files)
        if WRAPPERS[language] is not None:
            wrapper_patterns = WRAPPERS[language] if isinstance(WRAPPERS[language], list) else [WRAPPERS[language]]
            for pattern in wrapper_patterns:
                wrappers = project_absolute_path(
                    "benchmarks", "wrappers", deployment, language, pattern
                )
                for f in glob.glob(wrappers):
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
        return {"size": self.code_size, "hash": self.hash}

    def query_cache(self):

        if self.container_deployment:
            self._code_package = self._cache_client.get_container(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.language_name,
                language_version=self.language_version,
                architecture=self.architecture,
            )
            if self._code_package is not None:
                self._container_uri = self._code_package["image-uri"]
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
            language=self.language_name,
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

    def copy_code(self, output_dir):
        FILES = {
            "python": ["*.py", "requirements.txt*"],
            "nodejs": ["*.js", "package.json"],
            "rust": ["Cargo.toml", "Cargo.lock"],
            "java": [],
            "pypy": ["*.py", "requirements.txt*"],
        }
        path = os.path.join(self.benchmark_path, self.language_name)
        if self.language_name == "java":
            shutil.copytree(path, output_dir, dirs_exist_ok=True)
            return
        self.logging.info(f"copy_code: Looking for files in {path} for language {self.language_name}")
        for file_type in FILES[self.language_name]:
            matches = glob.glob(os.path.join(path, file_type))
            self.logging.info(f"copy_code: Pattern {file_type} matched {len(matches)} files: {matches}")
            for f in matches:
                self.logging.info(f"copy_code: Copying {f} to {output_dir}")
                shutil.copy2(f, output_dir)
        
        # For Rust, copy the entire src directory
        if self.language_name == "rust":
            src_path = os.path.join(path, "src")
            if os.path.exists(src_path):
                dest_src = os.path.join(output_dir, "src")
                if os.path.exists(dest_src):
                    shutil.rmtree(dest_src)
                shutil.copytree(src_path, dest_src)
        
        # support node.js benchmarks with language specific packages
        nodejs_package_json = os.path.join(path, f"package.json.{self.language_version}")
        if os.path.exists(nodejs_package_json):
            shutil.copy2(nodejs_package_json, os.path.join(output_dir, "package.json"))

    def add_benchmark_data(self, output_dir):
        cmd = "/bin/bash {benchmark_path}/init.sh {output_dir} false {architecture}"
        paths = [
            self.benchmark_path,
            os.path.join(self.benchmark_path, self.language_name),
        ]
        for path in paths:
            if os.path.exists(os.path.join(path, "init.sh")):
                subprocess.run(
                    cmd.format(
                        benchmark_path=path,
                        output_dir=output_dir,
                        architecture=self._experiment_config._architecture,
                    ),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )

    def _merge_rust_cargo_toml(self, wrapper_cargo_path: str, benchmark_cargo_path: str, output_dir: str):
        """
        Merge benchmark Cargo.toml dependencies into wrapper Cargo.toml.
        The wrapper Cargo.toml is the base, and benchmark dependencies are added/merged.
        Uses simple string-based approach to extract and merge [dependencies] sections.
        """
        import re
        
        # Ensure output_dir is absolute for consistent path handling
        output_dir = os.path.abspath(output_dir)
        
        with open(wrapper_cargo_path, 'r') as f:
            wrapper_content = f.read()
        
        with open(benchmark_cargo_path, 'r') as f:
            benchmark_content = f.read()
        
        # Extract dependencies from benchmark Cargo.toml
        deps_match = re.search(r'\[dependencies\](.*?)(?=\n\[|\Z)', benchmark_content, re.DOTALL)
        if not deps_match:
            # No dependencies in benchmark, just copy wrapper
            output_cargo = os.path.join(output_dir, "Cargo.toml")
            with open(output_cargo, 'w') as f:
                f.write(wrapper_content)
            return
        
        benchmark_deps_lines = deps_match.group(1).strip().split('\n')
        
        # Extract existing dependency names from wrapper to avoid duplicates
        wrapper_deps_match = re.search(r'\[dependencies\](.*?)(?=\n\[|\Z)', wrapper_content, re.DOTALL)
        existing_deps = set()
        if wrapper_deps_match:
            for line in wrapper_deps_match.group(1).split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Extract dependency name (before = or {)
                    dep_name = re.split(r'[=\s{]+', line)[0].strip()
                    if dep_name:
                        existing_deps.add(dep_name)
        
        # Add benchmark dependencies that aren't already in wrapper
        new_deps = []
        for line in benchmark_deps_lines:
            line = line.strip()
            if line and not line.startswith('#'):
                dep_name = re.split(r'[=\s{]+', line)[0].strip()
                if dep_name and dep_name not in existing_deps:
                    new_deps.append(line)
                    existing_deps.add(dep_name)
        
        # Merge dependencies into wrapper content
        if new_deps:
            if wrapper_deps_match:
                # Insert new dependencies before the end of [dependencies] section
                deps_section_start = wrapper_deps_match.start()
                deps_section_end = wrapper_deps_match.end()
                deps_content = wrapper_deps_match.group(1)
                
                # Build merged dependencies section
                merged_deps = deps_content.rstrip()
                for dep_line in new_deps:
                    merged_deps += '\n' + dep_line
                merged_deps += '\n'
                
                # Reconstruct wrapper content with merged dependencies
                merged_content = (
                    wrapper_content[:deps_section_start] +
                    '[dependencies]' + merged_deps +
                    wrapper_content[deps_section_end:]
                )
            else:
                # Add [dependencies] section if it doesn't exist
                if not wrapper_content.endswith('\n'):
                    wrapper_content += '\n'
                merged_content = wrapper_content + '\n[dependencies]\n'
                for dep_line in new_deps:
                    merged_content += dep_line + '\n'
        else:
            merged_content = wrapper_content
        
        # Write merged Cargo.toml (output_dir is already absolute)
        output_cargo = os.path.join(output_dir, "Cargo.toml")
        # Ensure directory exists
        os.makedirs(output_dir, exist_ok=True)
        with open(output_cargo, 'w') as f:
            f.write(merged_content)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        # Verify it was written (with a small delay for filesystem sync)
        import time
        time.sleep(0.01)  # Small delay for filesystem to sync
        if not os.path.exists(output_cargo):
            # Try to get more info about what went wrong
            parent_dir = os.path.dirname(output_cargo)
            raise RuntimeError(
                f"Failed to write merged Cargo.toml to {output_cargo}. "
                f"Parent directory exists: {os.path.exists(parent_dir)}, "
                f"Parent directory contents: {os.listdir(parent_dir) if os.path.exists(parent_dir) else 'N/A'}"
            )

    def add_deployment_files(self, output_dir):
        handlers_dir = project_absolute_path(
            "benchmarks", "wrappers", self._deployment_name, self.language_name
        )
        handlers = [
            os.path.join(handlers_dir, file)
            for file in self._system_config.deployment_files(
                self._deployment_name, self.language_name
            )
        ]
        
        # Copy wrapper files first (except Cargo.toml for Rust, which we'll merge)
        for file in handlers:
            destination = os.path.join(output_dir, os.path.basename(file))
            if os.path.basename(file) == "Cargo.toml" and self.language_name == "rust":
                # Skip copying wrapper Cargo.toml directly - we'll merge it instead
                continue
            if os.path.isdir(file):
                shutil.copytree(file, destination, dirs_exist_ok=True)
            else:
                if not os.path.exists(destination):
                    shutil.copy2(file, destination)
        
        # For Rust, merge Cargo.toml files after copying other wrapper files
        if self.language_name == "rust":
            # Ensure output_dir is absolute for consistent path handling
            output_dir_abs = os.path.abspath(output_dir)
            wrapper_cargo = os.path.join(handlers_dir, "Cargo.toml")
            benchmark_cargo = os.path.join(output_dir_abs, "Cargo.toml")
            self.logging.info(f"Rust Cargo.toml merge: wrapper={wrapper_cargo} (exists: {os.path.exists(wrapper_cargo)}), benchmark={benchmark_cargo} (exists: {os.path.exists(benchmark_cargo)})")
            if os.path.exists(wrapper_cargo) and os.path.exists(benchmark_cargo):
                # Merge dependencies from benchmark Cargo.toml into wrapper Cargo.toml
                self.logging.info("Merging Rust Cargo.toml files")
                # The merge function reads benchmark_cargo and writes merged content to output_dir/Cargo.toml
                # Since benchmark_cargo IS output_dir/Cargo.toml, the merge overwrites it
                # So we don't need to remove benchmark_cargo - it's already been overwritten with merged content
                self._merge_rust_cargo_toml(wrapper_cargo, benchmark_cargo, output_dir_abs)
                merged_path = os.path.join(output_dir_abs, "Cargo.toml")
                # The merge function should have raised an error if it failed, but verify anyway
                if not os.path.exists(merged_path):
                    # List directory contents for debugging
                    dir_contents = os.listdir(output_dir_abs) if os.path.exists(output_dir_abs) else []
                    raise RuntimeError(
                        f"Merged Cargo.toml was not created at {merged_path}. "
                        f"Directory contents: {dir_contents}"
                    )
                self.logging.info(f"Merged Cargo.toml successfully written to {merged_path}")
            elif os.path.exists(wrapper_cargo):
                # Only wrapper Cargo.toml exists, just copy it
                wrapper_dest = os.path.join(output_dir_abs, "Cargo.toml")
                self.logging.info(f"Only wrapper Cargo.toml exists, copying to {wrapper_dest}")
                shutil.copy2(wrapper_cargo, wrapper_dest)
            elif os.path.exists(benchmark_cargo):
                # Only benchmark Cargo.toml exists, copy it (shouldn't happen normally)
                benchmark_dest = os.path.join(output_dir_abs, "Cargo.toml")
                self.logging.warning(f"Only benchmark Cargo.toml exists, copying to {benchmark_dest}")
                # Keep it as-is since wrapper should always exist
            else:
                self.logging.error(f"Neither wrapper nor benchmark Cargo.toml found! Wrapper: {wrapper_cargo}, Benchmark: {benchmark_cargo}")
                raise RuntimeError(
                    f"Cargo.toml not found: wrapper at {wrapper_cargo} or benchmark at {benchmark_cargo}. "
                    "Both should exist for Rust builds."
                )

    def add_deployment_package_python(self, output_dir):

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
                if not package.endswith('\n'):
                    out.write('\n')

            module_packages = self._system_config.deployment_module_packages(
                self._deployment_name, self.language_name
            )
            for bench_module in self._benchmark_config.modules:
                if bench_module.value in module_packages:
                    for package in module_packages[bench_module.value]:
                        out.write(package)
                        if not package.endswith('\n'):
                            out.write('\n')

    def add_deployment_package_nodejs(self, output_dir):
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

    def add_deployment_package(self, output_dir):
        from sebs.faas.function import Language

        if self.language == Language.PYTHON or self.language == Language.PYPY:
            self.add_deployment_package_python(output_dir)
        elif self.language == Language.NODEJS:
            self.add_deployment_package_nodejs(output_dir)
        elif self.language == Language.RUST:
            # Rust dependencies are managed by Cargo, no additional packages needed
            pass
        elif self.language == Language.JAVA:
            # Java dependencies are handled by Maven in the wrapper
            return
        else:
            raise NotImplementedError

    @staticmethod
    def directory_size(directory: str):
        from pathlib import Path

        root = Path(directory)
        sizes = [f.stat().st_size for f in root.glob("**/*") if f.is_file()]
        return sum(sizes)

    def install_dependencies(self, output_dir):
        # do we have docker image for this run and language?
        image_types = self._system_config.docker_image_types(
            self._deployment_name, self.language_name
        )
        self.logging.info(
            f"Docker image types for {self._deployment_name}/{self.language_name}: {image_types}"
        )
        if "build" not in image_types:
            self.logging.info(
                (
                    "There is no Docker build image for {deployment} run in {language}, "
                    "thus skipping the Docker-based installation of dependencies."
                ).format(deployment=self._deployment_name, language=self.language_name)
            )
            # For Rust, this is a fatal error - we need the build image
            if self.language_name == "rust":
                raise RuntimeError(
                    f"Docker build image is required for Rust but not configured for "
                    f"{self._deployment_name}/{self.language_name}. "
                    "Please ensure 'build' is in the 'images' list in config/systems.json"
                )
        else:
            repo_name = self._system_config.docker_repository()
            unversioned_image_name = "build.{deployment}.{language}.{runtime}".format(
                deployment=self._deployment_name,
                language=self.language_name,
                runtime=self.language_version,
            )
            image_name = "{base_image_name}-{sebs_version}".format(
                base_image_name=unversioned_image_name,
                sebs_version=self._system_config.version(),
            )

            def ensure_image(name: str) -> None:
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

            try:
                ensure_image(image_name)
            except RuntimeError as e:
                self.logging.warning(
                    "Failed to ensure image {}, falling back to {}: {}".format(
                        image_name, unversioned_image_name, e
                    )
                )
                try:
                    ensure_image(unversioned_image_name)
                except RuntimeError:
                    raise
                # update `image_name` in the context to the fallback image name
                image_name = unversioned_image_name

            # Create set of mounted volumes unless Docker volumes are disabled
            if not self._experiment_config.check_flag("docker_copy_build_files"):
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
                
                # Mount updated java_installer.sh if language is java
                if self.language_name == "java":
                    installer_path = os.path.abspath("dockerfiles/java_installer.sh")
                    if os.path.exists(installer_path):
                        volumes[installer_path] = {
                            "bind": "/sebs/installer.sh",
                            "mode": "ro",
                        }

            # run Docker container to install packages
            PACKAGE_FILES = {"python": "requirements.txt", "nodejs": "package.json", "rust": "Cargo.toml", "java": "pom.xml", "pypy": "requirements.txt"}
            file = os.path.join(output_dir, PACKAGE_FILES[self.language_name])
            
            # For Java, check recursively if pom.xml exists
            if self.language_name == "java" and not os.path.exists(file):
                for root, _, files in os.walk(output_dir):
                    if "pom.xml" in files:
                        file = os.path.join(root, "pom.xml")
                        break

            self.logging.info(f"Checking for package file: {file} (exists: {os.path.exists(file)})")
            if os.path.exists(file):
                self.logging.info(f"Found package file {file}, proceeding with Docker build")
                try:
                    self.logging.info(
                        "Docker build of benchmark dependencies in container "
                        "of image {repo}:{image}".format(repo=repo_name, image=image_name)
                    )
                    uid = os.getuid()
                    # Standard, simplest build
                    if not self._experiment_config.check_flag("docker_copy_build_files"):
                        self.logging.info(
                            "Docker mount of benchmark code from path {path}".format(
                                path=os.path.abspath(output_dir)
                            )
                        )
                        stdout = self._docker_client.containers.run(
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
                            remove=True,
                            stdout=True,
                            stderr=True,
                        )
                    # Hack to enable builds on platforms where Docker mounted volumes
                    # are not supported. Example: CircleCI docker environment
                    else:
                        container = self._docker_client.containers.run(
                            "{}:{}".format(repo_name, image_name),
                            environment={"APP": self.benchmark},
                            # user="1000:1000",
                            user=uid,
                            remove=True,
                            detach=True,
                            tty=True,
                            command="/bin/bash",
                        )
                        # copy application files
                        import tarfile

                        self.logging.info(
                            "Send benchmark code from path {path} to "
                            "Docker instance".format(path=os.path.abspath(output_dir))
                        )
                        tar_archive = os.path.join(output_dir, os.path.pardir, "function.tar")
                        with tarfile.open(tar_archive, "w") as tar:
                            for f in os.listdir(output_dir):
                                tar.add(os.path.join(output_dir, f), arcname=f)
                        with open(tar_archive, "rb") as data:
                            container.put_archive("/mnt/function", data.read())
                        # do the build step
                        exit_code, stdout = container.exec_run(
                            cmd="/bin/bash /sebs/installer.sh",
                            user="docker_user",
                            stdout=True,
                            stderr=True,
                        )
                        # copy updated code with package
                        data, stat = container.get_archive("/mnt/function")
                        with open(tar_archive, "wb") as f:
                            for chunk in data:
                                f.write(chunk)
                        with tarfile.open(tar_archive, "r") as tar:
                            tar.extractall(output_dir)
                            # docker packs the entire directory with basename function
                            for f in os.listdir(os.path.join(output_dir, "function")):
                                shutil.move(
                                    os.path.join(output_dir, "function", f),
                                    os.path.join(output_dir, f),
                                )
                            shutil.rmtree(os.path.join(output_dir, "function"))
                        container.stop()

                    # Pass to output information on optimizing builds.
                    # Useful for AWS where packages have to obey size limits.
                    build_output = ""
                    if isinstance(stdout, bytes):
                        build_output = stdout.decode("utf-8")
                    elif isinstance(stdout, tuple):
                        # exec_run returns (exit_code, output)
                        exit_code, output = stdout
                        build_output = output.decode("utf-8") if isinstance(output, bytes) else str(output)
                        if exit_code != 0:
                            self.logging.error(f"Docker build exited with code {exit_code}")
                    else:
                        build_output = str(stdout)
                    
                    for line in build_output.split("\n"):
                        if "size" in line or "error" in line.lower() or "Error" in line or "failed" in line.lower():
                            self.logging.info("Docker build: {}".format(line))
                    
                    # For Rust, check if bootstrap binary was created
                    if self.language_name == "rust":
                        bootstrap_path = os.path.join(output_dir, "bootstrap")
                        if not os.path.exists(bootstrap_path):
                            self.logging.error("Rust build failed: bootstrap binary not found!")
                            self.logging.error("Build output:\n{}".format(build_output[-2000:]))  # Last 2000 chars
                            raise RuntimeError("Rust build failed: bootstrap binary not created")
                except docker.errors.ContainerError as e:
                    self.logging.error("Package build failed!")
                    self.logging.error(e)
                    self.logging.error(f"Docker mount volumes: {volumes}")
                    # For Rust, also check bootstrap even if ContainerError occurred
                    if self.language_name == "rust":
                        bootstrap_path = os.path.join(output_dir, "bootstrap")
                        if not os.path.exists(bootstrap_path):
                            self.logging.error("Rust bootstrap binary not found after Docker build failure!")
                    raise e
            else:
                # Package file doesn't exist
                error_msg = f"Package file {file} not found in {output_dir}"
                self.logging.error(error_msg)
                if self.language_name == "rust":
                    # List files in output_dir for debugging
                    files_in_dir = os.listdir(output_dir) if os.path.exists(output_dir) else []
                    self.logging.error(f"Files in output_dir: {files_in_dir}")
                    raise RuntimeError(
                        f"{error_msg}. For Rust, Cargo.toml must exist after merging wrapper and benchmark files. "
                        "Check that Cargo.toml merge completed successfully."
                    )

    def recalculate_code_size(self):
        self._code_size = Benchmark.directory_size(self._output_dir)
        return self._code_size

    def build(
        self,
        deployment_build_step: Callable[
            [str, str, str, str, str, bool, bool], Tuple[str, int, str]
        ],
    ) -> Tuple[bool, str, bool, str]:

        # Skip build if files are up to date and user didn't enforce rebuild
        if self.is_cached and self.is_cached_valid:
            self.logging.info(
                "Using cached benchmark {} at {}".format(self.benchmark, self.code_location)
            )
            if self.container_deployment:
                return False, self.code_location, self.container_deployment, self.container_uri

            return False, self.code_location, self.container_deployment, ""

        msg = (
            "no cached code package."
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
        
        # For Rust, remove any existing Cargo.lock to ensure it's regenerated with correct constraints
        if self.language_name == "rust":
            cargo_lock = os.path.join(self._output_dir, "Cargo.lock")
            if os.path.exists(cargo_lock):
                self.logging.info(f"Removing existing Cargo.lock at {cargo_lock} to ensure regeneration with correct dependency versions")
                os.remove(cargo_lock)
        
        self.install_dependencies(self._output_dir)
        
        # For Rust, verify bootstrap binary exists after dependency installation
        if self.language_name == "rust":
            bootstrap_path = os.path.join(self._output_dir, "bootstrap")
            if not os.path.exists(bootstrap_path):
                self.logging.error(f"Rust bootstrap binary not found at {bootstrap_path} after install_dependencies!")
                raise RuntimeError(
                    f"Rust build failed: bootstrap binary not created at {bootstrap_path}. "
                    "Check Docker build logs above for compilation errors."
                )

        self._code_location, self._code_size, self._container_uri = deployment_build_step(
            os.path.abspath(self._output_dir),
            self.language_name,
            self.language_version,
            self.architecture,
            self.benchmark,
            self.is_cached_valid,
            self.container_deployment,
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

        if self.is_cached:
            self._cache_client.update_code_package(self._deployment_name, self)
        else:
            self._cache_client.add_code_package(self._deployment_name, self)
        self.query_cache()

        return True, self._code_location, self._container_deployment, self._container_uri

    """
        Locates benchmark input generator, inspect how many storage buckets
        are needed and launches corresponding storage instance, if necessary.

        :param client: Deployment client
        :param benchmark:
        :param benchmark_path:
        :param size: Benchmark workload size
    """

    def prepare_input(
        self, system_resources: SystemResources, size: str, replace_existing: bool = False
    ):

        """
        Handle object storage buckets.
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
            for name, table_properties in self._benchmark_input_module.allocate_nosql().items():
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
            self._benchmark_data_path, size, bucket, input, output, storage_func, nosql_func
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

    """
        This is used in experiments that modify the size of input package.
        This step allows to modify code package without going through the entire pipeline.
    """

    def code_package_modify(self, filename: str, data: bytes):

        if self.code_package_is_archive():
            self._update_zip(self.code_location, filename, data)
            new_size = self.code_package_recompute_size() / 1024.0 / 1024.0
            self.logging.info(f"Modified zip package {self.code_location}, new size {new_size} MB")
        else:
            raise NotImplementedError()

    """
        AWS: .zip file
        Azure: directory
    """

    def code_package_is_archive(self) -> bool:
        if os.path.isfile(self.code_location):
            extension = os.path.splitext(self.code_location)[1]
            return extension in [".zip"]
        return False

    def code_package_recompute_size(self) -> float:
        bytes_size = os.path.getsize(self.code_location)
        self._code_size = bytes_size
        return bytes_size

    #  https://stackoverflow.com/questions/25738523/how-to-update-one-file-inside-zip-file-using-python
    @staticmethod
    def _update_zip(zipname: str, filename: str, data: bytes):
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


"""
    The interface of `input` module of each benchmark.
    Useful for static type hinting with mypy.
"""


class BenchmarkModuleInterface:
    @staticmethod
    @abstractmethod
    def buckets_count() -> Tuple[int, int]:
        pass

    @staticmethod
    @abstractmethod
    def allocate_nosql() -> dict:
        pass

    @staticmethod
    @abstractmethod
    def generate_input(
        data_dir: str,
        size: str,
        benchmarks_bucket: Optional[str],
        input_paths: List[str],
        output_paths: List[str],
        upload_func: Optional[Callable[[int, str, str], None]],
        nosql_func: Optional[
            Callable[[str, str, dict, Tuple[str, str], Optional[Tuple[str, str]]], None]
        ],
    ) -> Dict[str, str]:
        pass


def load_benchmark_input(benchmark_path: str) -> BenchmarkModuleInterface:
    # Look for input generator file in the directory containing benchmark
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("input", os.path.join(benchmark_path, "input.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod  # type: ignore

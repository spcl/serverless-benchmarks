from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import yaml
from sebs import benchmark
from sebs.faas.system import System
from sebs.faas.function import ExecutionResult, Function, Trigger
from sebs.faas.storage import PersistentStorage
from sebs.benchmark import Benchmark
from sebs.config import SeBSConfig
from sebs.cache import Cache
from sebs.utils import LoggingHandlers, execute
from sebs.knative.storage import KnativeMinio
from sebs.knative.triggers import LibraryTrigger, HTTPTrigger
from typing import Dict, Tuple, Type, List, Optional
import docker
from .function import KnativeFunction, KnativeFunctionConfig
from typing import cast
from .config import KnativeConfig


class Knative(System):
    _config: KnativeConfig

    def __init__(
        self,
        system_config: SeBSConfig,
        config: KnativeConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(system_config, cache_client, docker_client)
        self._config = config
        self._logging_handlers = logger_handlers

        if self.config.resources.docker_username:
            if self.config.resources.docker_registry:
                docker_client.login(
                    username=self.config.resources.docker_username,
                    password=self.config.resources.docker_password,
                    registry=self.config.resources.docker_registry,
                )
            else:
                docker_client.login(
                    username=self.config.resources.docker_username,
                    password=self.config.resources.docker_password,
                )

    def initialize(
        self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None
    ):
        self.initialize_resources(select_prefix=resource_prefix)

    @property
    def config(self) -> KnativeConfig:
        return self._config

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        if not hasattr(self, "storage"):

            if not self.config.resources.storage_config:
                raise RuntimeError(
                    "Knative is missing the configuration of pre-allocated storage!"
                )
            self.storage = KnativeMinio.deserialize(
                self.config.resources.storage_config,
                self.cache_client,
                self.config.resources,
            )
            self.storage.logging_handlers = self.logging_handlers
        else:
            self.storage.replace_existing = replace_existing
        return self.storage

    def shutdown(self) -> None:
        if hasattr(self, "storage") and self.config.shutdownStorage:
            self.storage.stop()
        if self.config.removeCluster:
            from tools.knative_setup import delete_cluster

            delete_cluster()
        super().shutdown()

    def sanitize_benchmark_name_for_knative(self, name: str) -> str:
        # Replace invalid characters with hyphens
        sanitized_name = re.sub(r"[^a-z0-9\-]+", "-", name.lower())
        # Ensure it starts with an alphabet
        sanitized_name_starts_with_alphabet = re.sub(r"^[^a-z]+", "", sanitized_name)
        # Ensure it ends with an alphanumeric character
        sanitized_benchmark_name = re.sub(
            r"[^a-z0-9]+$", "", sanitized_name_starts_with_alphabet
        )
        return sanitized_benchmark_name

    @staticmethod
    def name() -> str:
        return "knative"

    @staticmethod
    def typename():
        return "Knative"

    @staticmethod
    def function_type() -> Type[Function]:
        return KnativeFunction

    def get_knative_func_cmd(self) -> List[str]:
        cmd = [self.config.knative_exec]
        return cmd

    def find_image(self, repository_name, image_tag) -> bool:

        if self.config.experimentalManifest:
            try:
                # This requires enabling experimental Docker features
                # Furthermore, it's not yet supported in the Python library
                execute(f"docker manifest inspect {repository_name}:{image_tag}")
                return True
            except RuntimeError:
                return False
        else:
            try:
                # default version requires pulling for an image
                self.docker_client.images.pull(
                    repository=repository_name, tag=image_tag
                )
                return True
            except docker.errors.NotFound:
                return False

    def update_func_yaml_with_resources(self, directory: str, memory: int):
        yaml_path = os.path.join(directory, "func.yaml")

        with open(yaml_path, "r") as yaml_file:
            func_yaml_content = yaml.safe_load(yaml_file)

        if "run" in func_yaml_content:
            if "options" not in func_yaml_content:
                func_yaml_content["options"] = {}
            if "resources" not in func_yaml_content["options"]:
                func_yaml_content["options"]["resources"] = {}
            func_yaml_content["options"]["resources"]["requests"] = {"memory": memory}

        with open(yaml_path, "w") as yaml_file:
            yaml.dump(func_yaml_content, yaml_file, default_flow_style=False)

    def build_base_image(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> bool:
        """
        Build the base image for the function using the 'func build' command.

        Args:
        - directory: Directory where the function code resides.
        - language_name: Name of the programming language (e.g., Python).
        - language_version: Version of the programming language.
        - benchmark: Identifier for the benchmark or function.
        - is_cached: Flag indicating if the code is cached.

        Returns:
        - Boolean indicating if the image was built.
        """

        # Define the registry name
        registry_name = self.config.resources.docker_registry
        repository_name = self.system_config.docker_repository()
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version
        )

        if registry_name:
            repository_name = f"{registry_name}/{repository_name}"
        else:
            registry_name = "Docker Hub"

        if is_cached and self.find_image(repository_name, image_tag):
            self.logging.info(
                f"Skipping building Docker package for {benchmark}, using "
                f"Docker image {repository_name}:{image_tag} from registry: "
                f"{registry_name}."
            )
            return False
        else:
            self.logging.info(
                f"Image {repository_name}:{image_tag} doesn't exist in the registry, "
                f"building Docker package for {benchmark}."
            )

        # Fetch the base image for the specified language and version
        base_images = self.system_config.benchmark_base_images(
            self.name(), language_name
        )
        builder_image = base_images.get(language_version)

        # Construct the build command
        build_command = [
            "func",
            "build",
            "--builder",
            "s2i",
            "--builder-image",
            builder_image,
            "--registry",
            repository_name,
            "--path",
            directory,
            "--image",
            image_tag,
        ]

        self.logging.info(f"Running build command: {' '.join(build_command)}")

        try:
            result = subprocess.run(
                build_command,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Error building the function: {e.stderr.decode()}")
            raise RuntimeError(e) from e

        self.logging.info(
            f"Successfully built function image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )
        return True

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:
        """
        Package code for Knative platform by building a Docker image.

        Args:
        - directory: Directory where the function code resides.
        - language_name: Name of the programming language (e.g., Python).
        - language_version: Version of the programming language.
        - benchmark: Identifier for the benchmark or function.
        - is_cached: Flag indicating if the code is cached.

        Returns:
        - Tuple containing the Docker image name (tag) and its size.
        """

        CONFIG_FILES = {
            "python": [
                "func.py",
                "func.yaml",
                "Procfile",
                "requirements.txt",
                "app.sh",
            ],
            "nodejs": ["index.js", "func.yaml", "package.json"],
        }

        # Sanitize the benchmark name for the image tag
        sanitized_benchmark_name = self.sanitize_benchmark_name_for_knative(benchmark)
        # Generate func.yaml
        func_yaml_content = {
            "specVersion": "0.36.0",
            "name": sanitized_benchmark_name,
            "runtime": "node" if language_name == "nodejs" else language_name,
            "created": datetime.now().astimezone().isoformat(),
            "run": {
                "envs": [
                    {
                        "name": "MINIO_STORAGE_CONNECTION_URL",
                        "value": self.config._resources.storage_config.address,
                    },
                    {
                        "name": "MINIO_STORAGE_ACCESS_KEY",
                        "value": self.config._resources.storage_config.access_key,
                    },
                    {
                        "name": "MINIO_STORAGE_SECRET_KEY",
                        "value": self.config._resources.storage_config.secret_key,
                    },
                ]
            },
        }

        yaml_out = os.path.join(directory, "func.yaml")
        with open(yaml_out, "w") as yaml_file:
            yaml.dump(func_yaml_content, yaml_file, default_flow_style=False)

        # Create Procfile for Python runtime
        if language_name == "python":
            procfile_content = "web: python3 -m parliament ."
            procfile_out = os.path.join(directory, "Procfile")
            with open(procfile_out, "w") as procfile_file:
                procfile_file.write(procfile_content)

            # Create an empty __init__.py file
            init_file_out = os.path.join(directory, "__init__.py")
            open(init_file_out, "a").close()

            # Determine the correct requirements.txt file
            requirements_file = (
                f"requirements.txt.{language_version}"
                if language_version in ["3.9", "3.8", "3.7", "3.6"]
                else "requirements.txt"
            )
            requirements_src = os.path.join(directory, requirements_file)
            requirements_dst = os.path.join(directory, "requirements.txt")

            if os.path.exists(requirements_src):
                with open(requirements_src, "r") as src_file:
                    requirements_content = src_file.read()
                with open(requirements_dst, "a") as dst_file:
                    dst_file.write(requirements_content)
            # Create app.sh file for Python runtime
            app_sh_content = """#!/bin/sh
            exec python -m parliament "$(dirname "$0")"
            """
            app_sh_out = os.path.join(directory, "app.sh")
            with open(app_sh_out, "w") as app_sh_file:
                app_sh_file.write(app_sh_content)

            # Make app.sh executable
            os.chmod(app_sh_out, 0o755)

        # Modify package.json for Node.js runtime to add the faas-js-runtime.
        if language_name == "nodejs":
            package_json_path = os.path.join(directory, "package.json")
            if os.path.exists(package_json_path):
                with open(package_json_path, "r+") as package_file:
                    package_data = json.load(package_file)
                    if "scripts" not in package_data:
                        package_data["scripts"] = {}
                    package_data["scripts"]["start"] = "faas-js-runtime ./index.js"
                    package_file.seek(0)
                    package_file.write(json.dumps(package_data, indent=2))
                    package_file.truncate()

        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        # move all files to 'function' except func.py, func.yaml, Procfile
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        self.build_base_image(
            directory, language_name, language_version, benchmark, is_cached
        )

        code_size = Benchmark.directory_size(directory)
        return directory, code_size

    def storage_arguments(self) -> List[str]:
        storage = cast(KnativeMinio, self.get_storage())
        return [
            "-p",
            "MINIO_STORAGE_SECRET_KEY",
            storage.config.secret_key,
            "-p",
            "MINIO_STORAGE_ACCESS_KEY",
            storage.config.access_key,
            "-p",
            "MINIO_STORAGE_CONNECTION_URL",
            storage.config.address,
        ]

    def create_function(
        self, code_package: Benchmark, func_name: str
    ) -> "KnativeFunction":
        self.logging.info("Building Knative function")
        try:
            # Check if the function already exists
            knative_func_command = subprocess.run(
                [*self.get_knative_func_cmd(), "list"],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            )
            sanitize_benchmark_name = self.sanitize_benchmark_name_for_knative(
                code_package.benchmark
            )

            function_found = False
            docker_image = ""
            for line in knative_func_command.stdout.decode().split("\n"):
                if line and sanitize_benchmark_name in line.split()[0]:
                    function_found = True
                    break

            function_cfg = KnativeFunctionConfig.from_benchmark(code_package)
            function_cfg.storage = cast(KnativeMinio, self.get_storage()).config

            if function_found:
                self.logging.info(
                    f"Benchmark function of {sanitize_benchmark_name} already exists."
                )
                res = KnativeFunction(
                    sanitize_benchmark_name,
                    code_package.benchmark,
                    code_package.hash,
                    function_cfg,
                )
                self.logging.info(
                    f"Retrieved existing Knative function {sanitize_benchmark_name}"
                )
                self.update_function(res, code_package)
                return res

            else:
                try:
                    self.logging.info(
                        f"Deploying new Knative function {sanitize_benchmark_name}"
                    )
                    try:
                        docker_image = self.system_config.benchmark_image_name(
                            self.name(),
                            code_package.benchmark,
                            code_package.language_name,
                            code_package.language_version,
                        )
                        # Deploy the function
                        result = subprocess.run(
                            [
                                "func",
                                "deploy",
                                "--path",
                                code_package.code_location,
                            ],
                            capture_output=True,
                            check=True,
                        )
                        # Log the standard output
                        self.logging.info("Deployment succeeded:")
                        self.logging.info(
                            result.stdout.decode()
                        )  # Print the captured output
                    except subprocess.CalledProcessError as e:
                        # Log the standard error
                        self.logging.error("Deployment failed:")
                        self.logging.error(e.stderr.decode())

                    # Retrieve the function URL
                    describe_command = [
                        *self.get_knative_func_cmd(),
                        "describe",
                        sanitize_benchmark_name,
                        "-o",
                        "url",
                    ]
                    result = subprocess.run(
                        describe_command,
                        capture_output=True,
                        check=True,
                    )
                    function_url = result.stdout.decode().strip()
                    self.logging.info("Function deployment URL fetched successfully.")

                    function_cfg.url = function_url
                    function_cfg.docker_image = docker_image

                    # Create the function object
                    res = KnativeFunction(
                        sanitize_benchmark_name,
                        code_package.benchmark,
                        code_package.hash,
                        function_cfg,
                    )

                    # Add HTTP trigger with the function URL
                    trigger = LibraryTrigger(
                        sanitize_benchmark_name, self.get_knative_func_cmd()
                    )
                    trigger.logging_handlers = self.logging_handlers
                    res.add_trigger(trigger)

                    return res

                except subprocess.CalledProcessError as e:
                    self.logging.error(
                        f"Error deploying Knative function {sanitize_benchmark_name}."
                    )
                    self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
                    raise RuntimeError(e) from e

        except FileNotFoundError:
            self.logging.error(
                "Could not retrieve Knative functions - is path to func correct?"
            )
            raise RuntimeError("Failed to access func binary")

    def update_function(self, function: Function, code_package: Benchmark):
        self.logging.info(f"Updating an existing Knative function {function.name}.")
        function = cast(KnativeFunction, function)
        docker_image = self.system_config.benchmark_image_name(
            self.name(),
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
        )

        # Update func.yaml with resources before re-deployment
        self.update_func_yaml_with_resources(
            code_package.code_location, code_package.benchmark_config.memory
        )

        try:
            subprocess.run(
                [
                    *self.get_knative_func_cmd(),
                    "deploy",
                    "--path",
                    code_package.code_location,
                ],
                capture_output=True,
                check=True,
            )
            function.config.docker_image = docker_image

        except FileNotFoundError as e:
            self.logging.error(
                "Could not update Knative function - is the 'func' CLI installed and configured correctly?"
            )
            raise RuntimeError(e) from e
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error(
                "Ensure the SeBS cache is cleared if there are issues with Knative!"
            )
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

    def update_function_configuration(
        self, function: Function, code_package: Benchmark
    ):
        self.logging.info(
            f"Update configuration of an existing Knative function {function.name}."
        )

        self.update_func_yaml_with_resources(
            code_package.code_location, code_package.benchmark_config.memory
        )

        try:
            subprocess.run(
                [
                    "func",
                    "deploy",
                    "--path",
                    code_package.code_location,
                    "--push=false",
                ],
                capture_output=True,
                check=True,
            )

        except FileNotFoundError as e:
            self.logging.error(
                "Could not update Knative function - is path to func correct?"
            )
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error(
                "Make sure to remove SeBS cache after restarting Knative!"
            )
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)

    def create_trigger(
        self, function: Function, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        if trigger_type == Trigger.TriggerType.LIBRARY:
            return function.triggers(Trigger.TriggerType.LIBRARY)[0]
        elif trigger_type == Trigger.TriggerType.HTTP:
            try:
                response = subprocess.run(
                    [
                        *self.get_knative_func_cmd(),
                        "describe",
                        function.name,
                        "--output",
                        "url",
                    ],
                    capture_output=True,
                    check=True,
                )
            except FileNotFoundError as e:
                self.logging.error(
                    "Could not retrieve Knative function configuration - is the 'func' CLI installed and configured correctly?"
                )
                raise RuntimeError(e)
            stdout = response.stdout.decode("utf-8")
            url = stdout.strip()
            trigger = HTTPTrigger(function.name, url)
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)
            self.cache_client.update_function(function)
            return trigger
        else:
            raise RuntimeError("Not supported!")

    def cached_function(self, function: Function):
        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers

    def default_function_name(self, code_package: Benchmark) -> str:
        return (
            f"{code_package.benchmark}-{code_package.language_name}-"
            f"{code_package.language_version}"
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        raise NotImplementedError()

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        raise NotImplementedError()

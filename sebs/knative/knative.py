from os import devnull
import subprocess
from flask import config
from sebs.faas.system import System
from sebs.faas.function import Function, Trigger, ExecutionResult
from sebs.faas.storage import PersistentStorage
from sebs.benchmark import Benchmark
from sebs.config import SeBSConfig
from sebs.cache import Cache
from sebs.utils import LoggingHandlers
from sebs.knative.storage import KnativeMinio
from sebs.knative.triggers import KnativeLibraryTrigger, KnativeHTTPTrigger
from sebs.faas.config import Resources
from typing import Dict, Tuple, Type, List, Optional
import docker
from .function import KnativeFunction, KnativeFunctionConfig
import uuid
from typing import cast

from .config import KnativeConfig

class KnativeSystem(System):
    _config: KnativeConfig

    def __init__(self, system_config: SeBSConfig, config: KnativeConfig, cache_client: Cache, docker_client: docker.client, logger_handlers: LoggingHandlers):
        super().__init__(system_config, cache_client, docker_client)
        # Initialize any additional Knative-specific attributes here
        self._config = config
        self._logger_handlers = logger_handlers
     
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
         
     
    @property
    def config(self) -> KnativeConfig:
        # Return the configuration specific to Knative
        return self._config
    
    def get_knative_func_cmd(self) -> List[str]:
        cmd = [self.config.knative_exec]
        return cmd
    
    @staticmethod
    def function_type() -> Type[Function]:
        # Return the specific function type for Knative
        return Function

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        # Implementation of persistent storage retrieval for Knative
        # This might involve creating a persistent volume or bucket in Knative's ecosystem
        pass

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

        # Generate a unique Docker image name/tag for this function
        docker_image_name = f"{benchmark}:{language_version}"

        # Build Docker image from the specified directory
        image, _ = self._docker_client.images.build(path=directory, tag=docker_image_name)

        # Retrieve size of the Docker image
        image_size = image.attrs['Size']

        # Return the Docker image name (tag) and its size
        return docker_image_name, image_size


    def create_function(self, code_package: Benchmark, func_name: str) -> "KnativeFunction":
        self.logging.info("Creating Knative function.")
        try:
            # Check if the function already exists
            knative_func_command = subprocess.run(
                [*self.get_knative_func_cmd(), "list"],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
            )
            function_found = False
            for line in knative_func_command.stdout.decode().split("\n"):
                if line and func_name in line.split()[0]:
                    function_found = True
                    break

            if function_found:
                self.logging.info(f"Function {func_name} already exists.")
                # Logic for updating or handling existing function
                # For now, just pass
                pass
            else:
                try:
                    self.logging.info(f"Creating new Knative function {func_name}")
                    language = code_package.language_name

                    # Create the function
                    subprocess.run(
                        ["func", "create", "-l", language, func_name],
                        stderr=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        check=True,
                    )

                    # Deploy the function
                    subprocess.run(
                        ["func", "deploy", "--path", func_name],
                        stderr=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        check=True,
                    )

                    # Retrieve the function URL
                    describe_command = [*self.get_knative_func_cmd(), "describe", func_name, "-o", "url"]
                    result = subprocess.run(
                        describe_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True,
                    )
                    function_url = result.stdout.decode().strip()

                    # Create the KnativeFunctionConfig
                    function_cfg = KnativeFunctionConfig.from_benchmark(code_package)
                    function_cfg.storage = cast(KnativeMinio, self.get_storage()).config
                    function_cfg.url = function_url

                    # Create the function object
                    res = KnativeFunction(
                        func_name, code_package.benchmark, code_package.hash, function_cfg
                    )

                    # Add HTTP trigger with the function URL
                    trigger = KnativeHTTPTrigger(func_name, function_url)
                    trigger.logging_handlers = self.logging_handlers
                    res.add_trigger(trigger)

                    return res

                except subprocess.CalledProcessError as e:
                    self.logging.error(f"Error creating Knative function {func_name}.")
                    self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
                    raise RuntimeError(e)

        except FileNotFoundError:
            self.logging.error("Could not retrieve Knative functions - is path to func correct?")
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

        try:
            subprocess.run(
                [
                    "func", "deploy",
                    "--path", code_package.code_location,
                    "--image", docker_image,
                    "--name", function.name,
                ],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                check=True,
            )
            function.config.docker_image = docker_image

        except FileNotFoundError as e:
            self.logging.error("Could not update Knative function - is the 'func' CLI installed and configured correctly?")
            raise RuntimeError(e)
        except subprocess.CalledProcessError as e:
            self.logging.error(f"Unknown error when running function update: {e}!")
            self.logging.error("Ensure the SeBS cache is cleared if there are issues with Knative!")
            self.logging.error(f"Output: {e.stderr.decode('utf-8')}")
            raise RuntimeError(e)


    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        if trigger_type == Trigger.TriggerType.LIBRARY:
            return function.triggers(Trigger.TriggerType.LIBRARY)[0]
        elif trigger_type == Trigger.TriggerType.HTTP:
            try:
                response = subprocess.run(
                    ["func", "describe", function.name, "--output", "url"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except FileNotFoundError as e:
                self.logging.error(
                    "Could not retrieve Knative function configuration - is the 'func' CLI installed and configured correctly?"
                )
                raise RuntimeError(e)
            stdout = response.stdout.decode("utf-8")
            url = stdout.strip()
            trigger = KnativeHTTPTrigger(function.name, url)
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)
            self.cache_client.update_function(function)
            return trigger
        else:
            raise RuntimeError("Not supported!")


    @staticmethod
    def name() -> str:
        return "Knative"

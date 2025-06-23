"""Function and trigger implementations for local execution platform.

This module provides classes for managing functions and triggers in the local
execution environment. Functions run as Docker containers with HTTP triggers
for invocation.

Classes:
    HTTPTrigger: HTTP-based trigger for local function invocation
    LocalFunction: Represents a function deployed locally in a Docker container
"""

import concurrent.futures
import docker
import json
from typing import Optional

from sebs.utils import is_linux
from sebs.faas.function import ExecutionResult, Function, FunctionConfig, Trigger


class HTTPTrigger(Trigger):
    """HTTP trigger for local function invocation.

    Provides HTTP-based triggering for functions running in local Docker containers.
    Supports both synchronous and asynchronous invocation patterns.

    Attributes:
        url: HTTP URL endpoint for function invocation
    """

    def __init__(self, url: str):
        """Initialize HTTP trigger.

        Args:
            url: HTTP URL endpoint for the function
        """
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        """Get the type name for this trigger.

        Returns:
            str: Type name "Local.HTTPTrigger"
        """
        return "Local.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Get the trigger type.

        Returns:
            Trigger.TriggerType: HTTP trigger type
        """
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke the function via HTTP.

        Args:
            payload: Function input payload as dictionary

        Returns:
            ExecutionResult: Result of the function execution
        """
        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """Asynchronously invoke the function via HTTP.

        Args:
            payload: Function input payload as dictionary

        Returns:
            concurrent.futures.Future: Future object for the execution result
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        """Serialize trigger configuration to dictionary.

        Returns:
            dict: Dictionary containing trigger type and URL
        """
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """Deserialize trigger from dictionary.

        Args:
            obj: Dictionary containing trigger configuration

        Returns:
            HTTPTrigger: Deserialized HTTP trigger instance
        """
        return HTTPTrigger(obj["url"])


class LocalFunction(Function):
    """Function implementation for local execution platform.

    Represents a serverless function running locally in a Docker container.
    Handles container management, URL resolution, and memory measurement
    process tracking.

    Attributes:
        _instance: Docker container running the function
        _instance_id: Container ID for the function
        _port: Port number the function is listening on
        _url: Complete URL for function invocation
        _measurement_pid: Optional PID of memory measurement process
    """

    def __init__(
        self,
        docker_container,
        port: int,
        name: str,
        benchmark: str,
        code_package_hash: str,
        config: FunctionConfig,
        measurement_pid: Optional[int] = None,
    ):
        """Initialize local function.

        Args:
            docker_container: Docker container instance running the function
            port: Port number the function is listening on
            name: Function name
            benchmark: Benchmark name this function implements
            code_package_hash: Hash of the function code package
            config: Function configuration
            measurement_pid: Optional PID of memory measurement process

        Raises:
            RuntimeError: If container IP address cannot be determined
        """
        super().__init__(benchmark, name, code_package_hash, config)
        self._instance = docker_container
        self._instance_id = docker_container.id
        self._instance.reload()
        networks = self._instance.attrs["NetworkSettings"]["Networks"]
        self._port = port

        if is_linux():
            self._url = "{IPAddress}:{Port}".format(
                IPAddress=networks["bridge"]["IPAddress"], Port=port
            )
            if not self._url:
                self.logging.error(
                    f"Couldn't read the IP address of container from attributes "
                    f"{json.dumps(self._instance.attrs, indent=2)}"
                )
                raise RuntimeError(
                    f"Incorrect detection of IP address for container with id {self._instance_id}"
                )
        else:
            self._url = f"localhost:{port}"

        self._measurement_pid = measurement_pid

    @property
    def container(self) -> docker.models.containers.Container:
        """Get the Docker container running this function.

        Returns:
            docker.models.containers.Container: The Docker container instance
        """
        return self._instance

    @container.setter
    def container(self, instance: docker.models.containers.Container) -> None:
        """Set the Docker container for this function.

        Args:
            instance: New Docker container instance
        """
        self._instance = instance

    @property
    def url(self) -> str:
        """Get the URL for function invocation.

        Returns:
            str: HTTP URL for invoking the function
        """
        return self._url

    @property
    def memory_measurement_pid(self) -> Optional[int]:
        """Get the PID of the memory measurement process.

        Returns:
            Optional[int]: PID of memory measurement process, or None if not measuring
        """
        return self._measurement_pid

    @staticmethod
    def typename() -> str:
        """Get the type name for this function.

        Returns:
            str: Type name "Local.LocalFunction"
        """
        return "Local.LocalFunction"

    def serialize(self) -> dict:
        """Serialize function configuration to dictionary.

        Returns:
            dict: Dictionary containing function configuration including container details
        """
        return {
            **super().serialize(),
            "instance_id": self._instance_id,
            "url": self._url,
            "port": self._port,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "LocalFunction":
        """Deserialize function from cached configuration.

        Args:
            cached_config: Dictionary containing cached function configuration

        Returns:
            LocalFunction: Deserialized function instance

        Raises:
            RuntimeError: If cached container is no longer available
        """
        try:
            instance_id = cached_config["instance_id"]
            instance = docker.from_env().containers.get(instance_id)
            cfg = FunctionConfig.deserialize(cached_config["config"])
            return LocalFunction(
                instance,
                cached_config["port"],
                cached_config["name"],
                cached_config["benchmark"],
                cached_config["hash"],
                cfg,
            )
        except docker.errors.NotFound:
            raise RuntimeError(f"Cached container {instance_id} not available anymore!")

    def stop(self) -> None:
        """Stop the function container.

        Stops the Docker container running this function with immediate timeout.
        """
        self.logging.info(f"Stopping function container {self._instance_id}")
        self._instance.stop(timeout=0)
        self.logging.info(f"Function container {self._instance_id} stopped succesfully")

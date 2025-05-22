import concurrent.futures
import docker
import json
from typing import Optional

from sebs.utils import is_linux
from sebs.faas.function import ExecutionResult, Function, FunctionConfig, Trigger


class HTTPTrigger(Trigger):
    """
    Represents an HTTP trigger for a locally deployed function.
    The function is invoked via a URL, typically localhost or a container IP.
    """
    def __init__(self, url: str):
        """
        Initialize an HTTPTrigger.

        :param url: The invocation URL for the HTTP-triggered function.
        """
        super().__init__()
        self.url = url

    @staticmethod
    def typename() -> str:
        """Return the type name of this trigger implementation."""
        return "Local.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the type of this trigger (HTTP)."""
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the local function via its HTTP endpoint.

        :param payload: Input payload for the function (will be sent as JSON).
        :return: ExecutionResult object containing invocation details and metrics.
        """
        self.logging.debug(f"Invoke function {self.url}")
        # Assuming verify_ssl=False for local HTTP invocations, or it should be configurable.
        return self._http_invoke(payload, self.url, verify_ssl=False)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke the local function via its HTTP endpoint.

        Uses a ThreadPoolExecutor to perform the HTTP request in a separate thread.

        :param payload: Input payload for the function.
        :return: A Future object representing the asynchronous invocation.
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        """
        Serialize the HTTPTrigger to a dictionary.

        :return: Dictionary representation of the trigger, including type and URL.
        """
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        """
        Deserialize an HTTPTrigger from a dictionary.

        :param obj: Dictionary representation of the trigger, must contain 'url'.
        :return: A new HTTPTrigger instance.
        """
        return HTTPTrigger(obj["url"])


class LocalFunction(Function):
    """
    Represents a function deployed locally in a Docker container.

    Manages the Docker container instance, its URL, and associated metadata.
    """
    def __init__(
        self,
        docker_container: docker.models.containers.Container,
        port: int,
        name: str,
        benchmark: str,
        code_package_hash: str,
        config: FunctionConfig,
        measurement_pid: Optional[int] = None,
    ):
        """
        Initialize a LocalFunction instance.

        Determines the invocation URL based on the Docker container's network settings.

        :param docker_container: The Docker container instance running the function.
        :param port: The port on which the function is accessible within the container or host.
        :param name: Name of the local function.
        :param benchmark: Name of the benchmark this function belongs to.
        :param code_package_hash: Hash of the deployed code package.
        :param config: FunctionConfig object.
        :param measurement_pid: Optional PID of a process measuring memory for this function.
        :raises RuntimeError: If the IP address of the container cannot be determined on Linux.
        """
        super().__init__(benchmark, name, code_package_hash, config)
        self._instance = docker_container
        self._instance_id = docker_container.id
        self._instance.reload() # Ensure container attributes are up-to-date
        networks = self._instance.attrs.get("NetworkSettings", {}).get("Networks", {})
        self._port = port

        # Determine URL based on OS
        if is_linux():
            bridge_network = networks.get("bridge", {})
            ip_address = bridge_network.get("IPAddress")
            if not ip_address: # Fallback or error if IPAddress is empty or not found
                # Try to get gateway if IPAddress is empty, common in some Docker versions/networks
                ip_address = bridge_network.get("Gateway")
                if not ip_address:
                    self.logging.error(
                        f"Couldn't read IPAddress or Gateway for container {self._instance_id} "
                        f"from attributes: {json.dumps(self._instance.attrs, indent=2)}"
                    )
                    raise RuntimeError(
                        f"Incorrect detection of IP address for container {self._instance_id}"
                    )
            self._url = f"{ip_address}:{port}"
        else: # For non-Linux (e.g., Docker Desktop on macOS/Windows), localhost is typically used
            self._url = f"localhost:{port}"

        self._measurement_pid = measurement_pid

    @property
    def container(self) -> docker.models.containers.Container:
        """The Docker container instance for this function."""
        return self._instance

    @container.setter
    def container(self, instance: docker.models.containers.Container):
        """Set the Docker container instance."""
        self._instance = instance

    @property
    def url(self) -> str:
        """The invocation URL for this local function."""
        return self._url

    @property
    def memory_measurement_pid(self) -> Optional[int]:
        """The PID of the process measuring memory for this function, if any."""
        return self._measurement_pid

    @staticmethod
    def typename() -> str:
        """Return the type name of this function implementation."""
        return "Local.LocalFunction"

    def serialize(self) -> dict:
        """
        Serialize the LocalFunction instance to a dictionary.

        Includes instance ID, URL, and port along with base Function attributes.

        :return: Dictionary representation of the LocalFunction.
        """
        return {
            **super().serialize(),
            "instance_id": self._instance_id,
            "url": self._url,
            "port": self._port,
            # measurement_pid is runtime state, typically not serialized for cache/reuse
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "LocalFunction":
        """
        Deserialize a LocalFunction instance from a dictionary.

        Retrieves the Docker container instance using its ID.

        :param cached_config: Dictionary containing serialized LocalFunction data.
        :return: A new LocalFunction instance.
        :raises RuntimeError: If the cached Docker container is not found.
        """
        try:
            instance_id = cached_config["instance_id"]
            docker_client = docker.from_env()
            instance = docker_client.containers.get(instance_id)
            cfg = FunctionConfig.deserialize(cached_config["config"])
            # measurement_pid is runtime state, not restored from cache typically
            return LocalFunction(
                instance,
                cached_config["port"],
                cached_config["name"],
                cached_config["benchmark"],
                cached_config["hash"],
                cfg,
                measurement_pid=None # measurement_pid is runtime, not from cache
            )
        except docker.errors.NotFound:
            raise RuntimeError(f"Cached container {instance_id} not available anymore!")

    def stop(self):
        """Stop the Docker container associated with this function."""
        self.logging.info(f"Stopping function container {self._instance_id}")
        try:
            self._instance.stop(timeout=0) # timeout=0 for immediate stop
            self.logging.info(f"Function container {self._instance_id} stopped succesfully")
        except docker.errors.APIError as e:
            self.logging.error(f"Error stopping container {self._instance_id}: {e}")
            # Depending on desired behavior, might re-raise or handle

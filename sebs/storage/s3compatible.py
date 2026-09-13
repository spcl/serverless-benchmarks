# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""
Module for self-hosted, S3-compatible object storage in the Serverless Benchmarking Suite.

The storage runs in a Docker container and provides persistent storage for
benchmark data and results. It is primarily used for local testing and on
platforms with no object storage of their own, e.g., OpenWhisk. Concrete
implementations (MinIO, RustFS) only define the container image and its
configuration; the S3 client side is shared.
"""

import copy
import json
import os
import secrets
import uuid
from typing import Any, Dict, List, Optional, Type, TypeVar

import docker
import minio

from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.storage import PersistentStorage
from sebs.storage.config import S3CompatibleConfig
from sebs.utils import is_linux, probe_http, resolve_external_address


class S3CompatibleStorage(PersistentStorage):
    """
    This class manages a self-hosted, S3-compatible storage instance running
    in a Docker container. It handles bucket creation, file uploads/downloads,
    and container lifecycle management.

    Subclasses define the container image and how it is configured:

    Attributes:
        IMAGE: Docker image without a tag; the tag comes from the configuration's version
        COMMAND: Command passed to the container, or None for the image default
        ACCESS_KEY_ENV: Environment variable receiving the generated access key
        SECRET_KEY_ENV: Environment variable receiving the generated secret key
        HEALTH_PATH: HTTP path of the liveness endpoint
        BIND_MOUNT: Mount a host directory as the data volume and run the container
            as the host user. Otherwise, use a named Docker volume and the image's user.
        CONFIG_TYPE: Configuration class of the implementation
        config: Storage configuration settings
        connection: S3 client connection
    """

    IMAGE: str
    COMMAND: Optional[str]
    ACCESS_KEY_ENV: str
    SECRET_KEY_ENV: str
    HEALTH_PATH: str
    BIND_MOUNT: bool
    CONFIG_TYPE: Type[S3CompatibleConfig]

    @classmethod
    def typename(cls) -> str:
        """
        Get the qualified type name of this class.

        Returns:
            str: Full type name including deployment name
        """
        return f"{cls.deployment_name()}.{cls.__name__}"

    # The region setting is required by S3 API but not used for self-hosted storage
    S3_REGION = "us-east-1"

    def __init__(
        self,
        docker_client: docker.DockerClient,
        cache_client: Cache,
        resources: Resources,
        replace_existing: bool,
    ):
        """
        Initialize a storage instance.

        Args:
            docker_client: Docker client for managing the storage container
            cache_client: Cache client for storing storage configuration
            resources: Resources configuration
            replace_existing: Whether to replace existing buckets
        """
        super().__init__(self.S3_REGION, cache_client, resources, replace_existing)
        self._docker_client: docker.DockerClient = docker_client
        self._storage_container: Optional[docker.models.containers.Container] = None
        self._cfg: S3CompatibleConfig = self.CONFIG_TYPE()

    @property
    def config(self) -> S3CompatibleConfig:
        """
        Get the storage configuration.

        Returns:
            S3CompatibleConfig: The configuration object
        """
        return self._cfg

    @config.setter
    def config(self, config: S3CompatibleConfig):
        """
        Set the storage configuration.

        Args:
            config: New configuration object
        """
        self._cfg = config

    @staticmethod
    def _define_http_client() -> Any:
        """
        Configure HTTP client for the S3 client with appropriate timeouts and retries.

        The MinIO SDK does not provide a direct way to configure connection timeouts, so
        we need to create a custom HTTP client with proper timeout settings.
        The rest of configuration follows the SDK's default client settings.

        Returns:
            urllib3.PoolManager: Configured HTTP client
        """
        import urllib3
        from datetime import timedelta

        timeout = timedelta(seconds=1).seconds

        return urllib3.PoolManager(
            timeout=urllib3.util.Timeout(connect=timeout, read=timeout),
            maxsize=10,
            retries=urllib3.Retry(
                total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]
            ),
        )

    def start(self) -> None:
        """
        Start the storage container.

        Creates and runs the Docker container, configuring it with
        random credentials and mounting a volume for persistent storage.
        The container runs in detached mode and is accessible via the
        configured port.

        Raises:
            RuntimeError: If starting the container fails
        """
        name = self.deployment_name()
        # Set up data volume: a host directory, or a named Docker volume
        if self._cfg.data_volume == "":
            self._cfg.data_volume = f"{name}-volume"
        if self.BIND_MOUNT:
            self._cfg.data_volume = os.path.abspath(self._cfg.data_volume)
            os.makedirs(self._cfg.data_volume, exist_ok=True)
        volumes = {self._cfg.data_volume: {"bind": "/data", "mode": "rw"}}

        # Generate random credentials for security
        self._cfg.access_key = secrets.token_urlsafe(32)
        self._cfg.secret_key = secrets.token_hex(32)
        self._cfg.address = ""
        self.logging.info(f"{name} storage ACCESS_KEY={self._cfg.access_key}")
        self.logging.info(f"{name} storage SECRET_KEY={self._cfg.secret_key}")

        try:
            self.logging.info(f"Starting storage {name} on port {self._cfg.mapped_port}")
            self._storage_container = self._docker_client.containers.run(
                f"{self.IMAGE}:{self._cfg.version}",
                command=self.COMMAND,
                network_mode="bridge",
                user=os.getuid() if self.BIND_MOUNT else None,
                ports={"9000": self._cfg.mapped_port},
                environment={
                    self.ACCESS_KEY_ENV: self._cfg.access_key,
                    self.SECRET_KEY_ENV: self._cfg.secret_key,
                },
                volumes=volumes,
                remove=self.config.remove_containers,
                stdout=True,
                stderr=True,
                detach=True,
            )
            assert self._storage_container.id is not None
            self._cfg.instance_id = self._storage_container.id
            self.configure_connection()
        except docker.errors.APIError as e:
            self.logging.error(f"Starting {name} storage failed! Reason: {e}")
            raise RuntimeError(f"Starting {name} storage unsuccessful")
        except Exception as e:
            self.logging.error(f"Starting {name} storage failed! Unknown error: {e}")
            raise RuntimeError(f"Starting {name} storage unsuccessful")

    def configure_connection(self) -> None:
        """
        Configure the connection to the storage container.

        Determines the appropriate address to connect to the container
        based on the host platform. For Linux, it uses the container's
        bridge IP address, while for Windows, macOS, or WSL it uses
        localhost with the mapped port.

        Additionally, it determines the address advertised to benchmark
        functions: the user-provided external address, or the host's
        default-route IP combined with the mapped port. This address is
        reachable from outside the Docker bridge network, e.g., from
        Kubernetes pods.

        Raises:
            RuntimeError: If the container is not available or if the IP address
                          cannot be detected
        """
        # Only configure if the address is not already set
        if self._cfg.address == "":
            # Verify container existence
            if self._storage_container is None:
                raise RuntimeError(
                    "Storage container is not available! Make sure that you deployed "
                    "the Minio storage and provided configuration!"
                )

            # Reload to ensure we have the latest container attributes
            self._storage_container.reload()

            # Platform-specific address configuration
            if is_linux():
                # On native Linux, use the container's bridge network IP
                networks = self._storage_container.attrs["NetworkSettings"]["Networks"]
                self._cfg.address = "{IPAddress}:{Port}".format(
                    IPAddress=networks["bridge"]["IPAddress"], Port=9000
                )
            else:
                # On Windows, macOS, or WSL, use localhost with the mapped port
                self._cfg.address = f"localhost:{self._cfg.mapped_port}"

            # Verify address was successfully determined
            if not self._cfg.address:
                self.logging.error(
                    f"Couldn't read the IP address of container from attributes "
                    f"{json.dumps(self._storage_container.attrs, indent=2)}"
                )
                raise RuntimeError(
                    f"Incorrect detection of IP address for container with id "
                    f"{self._cfg.instance_id}"
                )
            self.logging.info(f"Starting {self.deployment_name()} instance at {self._cfg.address}")
            self.configure_external_address()

        # Create the connection using the configured address
        self.connection = self.get_connection()

    def configure_external_address(self) -> None:
        """
        Determine the address advertised to benchmark functions.

        Uses the user-provided external address, or the host's default-route IP,
        combined with the mapped port.
        """
        name = self.deployment_name()
        self._cfg.external_address = resolve_external_address(
            self._cfg.external_address, self._cfg.mapped_port
        )
        if self._cfg.external_address:
            self.logging.info(f"{name} advertised to functions at {self._cfg.external_address}")
        else:
            self.logging.warning(
                "Could not detect the host's IP address. Functions running outside of the "
                f"Docker bridge network will not reach {name}; provide --external-address."
            )

    def check_external_address(self) -> bool:
        """
        Verify that the storage is reachable through the address advertised to functions.

        Failures are reported as warnings, since the host running SeBS is not
        always able to reach the same network as benchmark functions.

        Returns:
            bool: True if the probe succeeded
        """
        if not self._cfg.external_address:
            return False
        name = self.deployment_name()
        url = f"http://{self._cfg.external_address}{self.HEALTH_PATH}"
        error = probe_http(url, timeout_seconds=15)
        if error is None:
            self.logging.info(f"{name} is reachable at {url}")
            return True
        self.logging.warning(
            f"{name} is not reachable at {url}: {error}. Benchmark functions might not be "
            f"able to reach the storage. Verify the address with: curl -i {url}"
        )
        return False

    def stop(self) -> None:
        """
        Stop the storage container.

        Gracefully stops the running MinIO container if it exists.
        Logs an error if the container is not known.
        """
        if self._storage_container is not None:
            self.logging.info(f"Stopping storage container at {self._cfg.address}.")
            self._storage_container.stop()
            self.logging.info(f"Stopped storage container at {self._cfg.address}.")
        else:
            self.logging.error("Stopping storage was not successful, container not known!")

    def get_connection(self) -> minio.Minio:
        """
        Create a new S3 client connection.

        Creates a connection to the storage server using the configured address,
        credentials, and HTTP client settings.

        Returns:
            minio.Minio: Configured S3 client from the MinIO SDK
        """
        return minio.Minio(
            self._cfg.address,
            access_key=self._cfg.access_key,
            secret_key=self._cfg.secret_key,
            secure=False,  # Self-hosted storage doesn't use HTTPS
            http_client=self._define_http_client(),
        )

    def _create_bucket(
        self,
        name: str,
        buckets: Optional[List[str]] = None,
        randomize_name: bool = False,
    ) -> str:
        """
        Create a new bucket if it doesn't already exist.

        Checks if a bucket with the given name already exists in the list of buckets.
        If not, creates a new bucket with either the exact name or a randomized name.

        Args:
            name: Base name for the bucket
            buckets: List of existing bucket names to check against
            randomize_name: Whether to append a random UUID to the bucket name

        Returns:
            str: Name of the existing or newly created bucket

        Raises:
            minio.error.ResponseError: If bucket creation fails
        """

        if buckets is None:
            buckets = []

        # Check if bucket already exists
        for bucket_name in buckets:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(bucket_name, name)
                )
                return bucket_name

        # Bucket names are limited to 16 characters
        if randomize_name:
            bucket_name = "{}-{}".format(name, str(uuid.uuid4())[0:16])
        else:
            bucket_name = name

        try:
            self.connection.make_bucket(bucket_name, location=self.S3_REGION)
            self.logging.info("Created bucket {}".format(bucket_name))
            return bucket_name
        except (
            minio.error.BucketAlreadyOwnedByYou,
            minio.error.BucketAlreadyExists,
            minio.error.ResponseError,
        ) as err:
            self.logging.error("Bucket creation failed!")
            # Rethrow the error for handling by the caller
            raise err

    def uploader_func(self, path_idx: int, file: str, filepath: str) -> None:
        """
        Upload a file to the storage.

        Uploads a file to the specified input prefix in the benchmarks bucket.
        This function is passed to benchmarks for uploading their input data.

        Args:
            path_idx: Index of the input prefix to use
            file: Name of the file within the bucket
            filepath: Local path to the file to upload

        Raises:
            minio.error.ResponseError: If the upload fails
        """
        try:
            key = os.path.join(self.input_prefixes[path_idx], file)
            bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
            self.logging.info("Upload {} to {}".format(filepath, bucket_name))
            self.connection.fput_object(bucket_name, key, filepath)
        except minio.error.ResponseError as err:
            self.logging.error("Upload failed!")
            raise err

    def clean_bucket(self, bucket_name: str) -> None:
        """
        Remove all objects from a bucket.

        Deletes all objects within the specified bucket but keeps the bucket itself.
        Logs any errors that occur during object deletion.

        Args:
            bucket: Name of the bucket to clean
        """
        delete_object_list = map(
            lambda x: minio.DeleteObject(x.object_name),
            self.connection.list_objects(bucket_name=bucket_name),
        )
        errors = self.connection.remove_objects(bucket_name, delete_object_list)
        for error in errors:
            self.logging.error(f"Error when deleting object from bucket {bucket_name}: {error}!")

    def remove_bucket(self, bucket: str) -> None:
        """
        Delete a bucket completely.

        Removes the specified bucket from the storage.
        The bucket must be empty before it can be deleted.

        Args:
            bucket: Name of the bucket to remove
        """
        self.connection.remove_bucket(Bucket=bucket)

    def correct_name(self, name: str) -> str:
        """
        Format a bucket name to comply with naming requirements.

        No name correction is needed (unlike some cloud providers
        that enforce additional restrictions).

        Args:
            name: Original bucket name

        Returns:
            str: Bucket name (unchanged)
        """
        return name

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """
        Download an object from a bucket to a local file.

        Args:
            bucket_name: Name of the source bucket
            key: Object key/path in the bucket
            filepath: Local destination path

        Raises:
            RuntimeError: If the bucket does not exist
            minio.error.ResponseError: If the download fails
        """
        if not self.exists_bucket(bucket_name):
            raise RuntimeError(f"Attempting to download from a non-existing bucket {bucket_name}!")
        try:
            self.connection.fget_object(bucket_name, key, filepath)
        except minio.error.ResponseError as err:
            raise err

    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if a bucket exists.

        Args:
            bucket_name: Name of the bucket to check

        Returns:
            bool: True if the bucket exists, False otherwise
        """
        return self.connection.bucket_exists(bucket_name)

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        List all objects in a bucket with an optional prefix filter.

        Args:
            bucket_name: Name of the bucket to list
            prefix: Optional prefix to filter objects

        Returns:
            List[str]: List of object names in the bucket

        Raises:
            RuntimeError: If the bucket does not exist
        """
        try:
            objects_list = self.connection.list_objects(bucket_name)
            return [obj.object_name for obj in objects_list if prefix in obj.object_name]
        except minio.error.NoSuchBucket:
            raise RuntimeError(
                f"Attempting to access a non-existing bucket {bucket_name}!"
            ) from None

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List all buckets, optionally filtered by name.

        Args:
            bucket_name: Optional filter for bucket names

        Returns:
            List[str]: List of bucket names
        """
        buckets = self.connection.list_buckets()
        if bucket_name is not None:
            return [bucket.name for bucket in buckets if bucket_name in bucket.name]
        else:
            return [bucket.name for bucket in buckets]

    def upload(self, bucket_name: str, filepath: str, key: str) -> None:
        """
        Upload a file to a bucket.

        Not implemented for this class. Use fput_object directly or uploader_func.

        Raises:
            NotImplementedError: This method is not implemented
        """
        raise NotImplementedError()

    def serialize(self) -> Dict[str, Any]:
        """
        Serialize the storage configuration to a dictionary.

        Returns:
            dict: Serialized configuration data
        """
        return self._cfg.serialize()

    T = TypeVar("T", bound="S3CompatibleStorage")

    @staticmethod
    def _deserialize(
        cached_config: S3CompatibleConfig,
        cache_client: Cache,
        resources: Resources,
        obj_type: Type[T],
    ) -> T:
        """
        Deserialize a storage instance from cached configuration with custom type.

        Creates a new instance of the specified class type from cached configuration
        data. This allows platform-specific versions to be deserialized correctly
        while sharing the core implementation. When overriding the implementation in
        Local/OpenWhisk/..., we call the _deserialize method and provide an
        alternative implementation type.

        FIXME: is this still needed? It looks like we stopped using
        platform-specific implementations.

        Args:
            cached_config: Cached storage configuration
            cache_client: Cache client
            resources: Resources configuration
            obj_type: Type of object to create (a S3CompatibleStorage subclass)

        Returns:
            T: Deserialized instance of the specified type

        Raises:
            RuntimeError: If the storage container does not exist
        """
        docker_client = docker.from_env()
        obj = obj_type(docker_client, cache_client, resources, False)
        obj._cfg = cached_config

        # Try to reconnect to existing container if ID is available
        if cached_config.instance_id:
            instance_id = cached_config.instance_id
            try:
                obj._storage_container = docker_client.containers.get(instance_id)
            except docker.errors.NotFound:
                raise RuntimeError(f"Storage container {instance_id} does not exist!")
        else:
            obj._storage_container = None

        # Copy bucket information
        obj._input_prefixes = copy.copy(cached_config.input_buckets)
        obj._output_prefixes = copy.copy(cached_config.output_buckets)

        # Set up connection
        obj.configure_connection()
        return obj

    @classmethod
    def deserialize(
        cls: Type[T], cached_config: S3CompatibleConfig, cache_client: Cache, res: Resources
    ) -> T:
        """
        Deserialize a storage instance from cached configuration.

        Args:
            cached_config: Cached storage configuration
            cache_client: Cache client
            res: Resources configuration

        Returns:
            T: Deserialized instance of the calling class
        """
        return cls._deserialize(cached_config, cache_client, res, cls)

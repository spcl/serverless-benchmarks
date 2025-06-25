"""
Module for MinIO S3-compatible storage in the Serverless Benchmarking Suite.

This module implements local object storage using MinIO, which provides an
S3-compatible API. MinIO runs in a Docker container and provides persistent
storage for benchmark data and results. It is primarily used for local
testing and development of S3-dependent serverless functions.
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
from sebs.storage.config import MinioConfig
from sebs.utils import project_absolute_path
from sebs.utils import is_linux


class Minio(PersistentStorage):
    """
    S3-compatible object storage implementation using MinIO.

    This class manages a MinIO storage instance running in a Docker container,
    providing S3-compatible object storage for local benchmarking. It handles
    bucket creation, file uploads/downloads, and container lifecycle management.

    Attributes:
        config: MinIO configuration settings
        connection: MinIO client connection
    """

    @staticmethod
    def typename() -> str:
        """
        Get the qualified type name of this class.

        Returns:
            str: Full type name including deployment name
        """
        return f"{Minio.deployment_name()}.Minio"

    @staticmethod
    def deployment_name() -> str:
        """
        Get the deployment platform name.

        Returns:
            str: Deployment name ('minio')
        """
        return "minio"

    # The region setting is required by S3 API but not used for local MinIO
    MINIO_REGION = "us-east-1"

    def __init__(
        self,
        docker_client: docker.DockerClient,
        cache_client: Cache,
        resources: Resources,
        replace_existing: bool,
    ):
        """
        Initialize a MinIO storage instance.

        Args:
            docker_client: Docker client for managing the MinIO container
            cache_client: Cache client for storing storage configuration
            resources: Resources configuration
            replace_existing: Whether to replace existing buckets
        """
        super().__init__(self.MINIO_REGION, cache_client, resources, replace_existing)
        self._docker_client: docker.DockerClient = docker_client
        self._storage_container: Optional[docker.models.containers.Container] = None
        self._cfg = MinioConfig()

    @property
    def config(self) -> MinioConfig:
        """
        Get the MinIO configuration.

        Returns:
            MinioConfig: The configuration object
        """
        return self._cfg

    @config.setter
    def config(self, config: MinioConfig):
        """
        Set the MinIO configuration.

        Args:
            config: New configuration object
        """
        self._cfg = config

    @staticmethod
    def _define_http_client() -> Any:
        """
        Configure HTTP client for MinIO with appropriate timeouts and retries.

        MinIO does not provide a direct way to configure connection timeouts, so
        we need to create a custom HTTP client with proper timeout settings.
        The rest of configuration follows MinIO's default client settings.

        Returns:
            urllib3.PoolManager: Configured HTTP client for MinIO
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
        Start a MinIO storage container.

        Creates and runs a Docker container with MinIO, configuring it with
        random credentials and mounting a volume for persistent storage.
        The container runs in detached mode and is accessible via the
        configured port.

        Raises:
            RuntimeError: If starting the MinIO container fails
        """
        # Set up data volume location
        if self._cfg.data_volume == "":
            minio_volume = os.path.join(project_absolute_path(), "minio-volume")
        else:
            minio_volume = self._cfg.data_volume
        minio_volume = os.path.abspath(minio_volume)

        # Create volume directory if it doesn't exist
        os.makedirs(minio_volume, exist_ok=True)
        volumes = {
            minio_volume: {
                "bind": "/data",
                "mode": "rw",
            }
        }

        # Generate random credentials for security
        self._cfg.access_key = secrets.token_urlsafe(32)
        self._cfg.secret_key = secrets.token_hex(32)
        self._cfg.address = ""
        self.logging.info("Minio storage ACCESS_KEY={}".format(self._cfg.access_key))
        self.logging.info("Minio storage SECRET_KEY={}".format(self._cfg.secret_key))

        try:
            self.logging.info(f"Starting storage Minio on port {self._cfg.mapped_port}")
            # Run the MinIO container
            self._storage_container = self._docker_client.containers.run(
                f"minio/minio:{self._cfg.version}",
                command="server /data",
                network_mode="bridge",
                ports={"9000": str(self._cfg.mapped_port)},
                environment={
                    "MINIO_ACCESS_KEY": self._cfg.access_key,
                    "MINIO_SECRET_KEY": self._cfg.secret_key,
                },
                volumes=volumes,
                remove=True,
                stdout=True,
                stderr=True,
                detach=True,
            )
            self._cfg.instance_id = self._storage_container.id
            self.configure_connection()
        except docker.errors.APIError as e:
            self.logging.error("Starting Minio storage failed! Reason: {}".format(e))
            raise RuntimeError("Starting Minio storage unsuccesful")
        except Exception as e:
            self.logging.error("Starting Minio storage failed! Unknown error: {}".format(e))
            raise RuntimeError("Starting Minio storage unsuccesful")

    def configure_connection(self) -> None:
        """
        Configure the connection to the MinIO container.

        Determines the appropriate address to connect to the MinIO container
        based on the host platform. For Linux, it uses the container's IP address,
        while for Windows, macOS, or WSL it uses localhost with the mapped port.

        Raises:
            RuntimeError: If the MinIO container is not available or if the IP address
                          cannot be detected
        """
        # Only configure if the address is not already set
        if self._cfg.address == "":
            # Verify container existence
            if self._storage_container is None:
                raise RuntimeError(
                    "Minio container is not available! Make sure that you deployed "
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
            self.logging.info("Starting minio instance at {}".format(self._cfg.address))

        # Create the connection using the configured address
        self.connection = self.get_connection()

    def stop(self) -> None:
        """
        Stop the MinIO container.

        Gracefully stops the running MinIO container if it exists.
        Logs an error if the container is not known.
        """
        if self._storage_container is not None:
            self.logging.info(f"Stopping minio container at {self._cfg.address}.")
            self._storage_container.stop()
            self.logging.info(f"Stopped minio container at {self._cfg.address}.")
        else:
            self.logging.error("Stopping minio was not successful, storage container not known!")

    def get_connection(self) -> minio.Minio:
        """
        Create a new MinIO client connection.

        Creates a connection to the MinIO server using the configured address,
        credentials, and HTTP client settings.

        Returns:
            minio.Minio: Configured MinIO client
        """
        return minio.Minio(
            self._cfg.address,
            access_key=self._cfg.access_key,
            secret_key=self._cfg.secret_key,
            secure=False,  # Local MinIO doesn't use HTTPS
            http_client=Minio._define_http_client(),
        )

    def _create_bucket(
        self, name: str, buckets: Optional[List[str]] = None, randomize_name: bool = False
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

        # MinIO has limit of bucket name to 16 characters
        if randomize_name:
            bucket_name = "{}-{}".format(name, str(uuid.uuid4())[0:16])
        else:
            bucket_name = name

        try:
            self.connection.make_bucket(bucket_name, location=self.MINIO_REGION)
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
        Upload a file to the MinIO storage.

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
            self.connection.fput_object(bucket_name, key, filepath)
        except minio.error.ResponseError as err:
            self.logging.error("Upload failed!")
            raise err

    # FIXME: is still even used anywhere?
    # def clean(self) -> None:
    #     """
    #     Clean all objects from output buckets.

    #     Removes all objects from the output buckets to prepare for a new
    #     benchmark run. Logs any errors that occur during deletion.
    #     """
    #     for bucket in self.output_buckets:
    #         objects = self.connection.list_objects_v2(bucket)
    #         objects = [obj.object_name for obj in objects]
    #         for err in self.connection.remove_objects(bucket, objects):
    #             self.logging.error("Deletion Error: {}".format(err))
    #
    # def download_results(self, result_dir: str) -> None:
    #    """
    #    Download all objects from output buckets to a local directory.

    #    Downloads benchmark results from all output buckets to a subdirectory
    #    named 'storage_output' within the specified result directory.

    #    Args:
    #        result_dir: Base directory to store downloaded results
    #    """
    #    result_dir = os.path.join(result_dir, "storage_output")
    #    for bucket in self.output_buckets:
    #        objects = self.connection.list_objects_v2(bucket)
    #        objects = [obj.object_name for obj in objects]
    #        for obj in objects:
    #            self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))

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

        Removes the specified bucket from the MinIO storage.
        The bucket must be empty before it can be deleted.

        Args:
            bucket: Name of the bucket to remove
        """
        self.connection.remove_bucket(Bucket=bucket)

    def correct_name(self, name: str) -> str:
        """
        Format a bucket name to comply with MinIO naming requirements.

        For MinIO, no name correction is needed (unlike some cloud providers
        that enforce additional restrictions).

        Args:
            name: Original bucket name

        Returns:
            str: Bucket name (unchanged for MinIO)
        """
        return name

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """
        Download an object from a bucket to a local file.

        Not implemented for this class. Use fget_object directly or other methods.

        Raises:
            NotImplementedError: This method is not implemented
        """
        raise NotImplementedError()

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
            raise RuntimeError(f"Attempting to access a non-existing bucket {bucket_name}!")

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
        Serialize MinIO configuration to a dictionary.

        Returns:
            dict: Serialized configuration data
        """
        return self._cfg.serialize()

    """
    Deserialization and inheritance support

    This implementation supports overriding this class. The main Minio class
    is used to start/stop deployments. When overriding the implementation in
    Local/OpenWhisk/..., we call the _deserialize method and provide an
    alternative implementation type.
    """

    T = TypeVar("T", bound="Minio")

    @staticmethod
    def _deserialize(
        cached_config: MinioConfig,
        cache_client: Cache,
        resources: Resources,
        obj_type: Type[T],
    ) -> T:
        """
        Deserialize a MinIO instance from cached configuration with custom type.

        Creates a new instance of the specified class type from cached configuration
        data. This allows platform-specific versions to be deserialized correctly
        while sharing the core implementation.

        Args:
            cached_config: Cached MinIO configuration
            cache_client: Cache client
            resources: Resources configuration
            obj_type: Type of object to create (a Minio subclass)

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

    @staticmethod
    def deserialize(cached_config: MinioConfig, cache_client: Cache, res: Resources) -> "Minio":
        """
        Deserialize a MinIO instance from cached configuration.

        Creates a new Minio instance from cached configuration data.

        Args:
            cached_config: Cached MinIO configuration
            cache_client: Cache client
            res: Resources configuration

        Returns:
            Minio: Deserialized Minio instance
        """
        return Minio._deserialize(cached_config, cache_client, res, Minio)

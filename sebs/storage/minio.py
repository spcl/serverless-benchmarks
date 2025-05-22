import copy
import json
import os
import secrets
import uuid
from typing import List, Optional, Type, TypeVar

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
    Persistent storage implementation using a self-hosted Minio S3-compatible server
    running in a Docker container.
    """
    @staticmethod
    def typename() -> str:
        """Return the type name of this storage implementation."""
        return f"{Minio.deployment_name()}.Minio"

    @staticmethod
    def deployment_name() -> str:
        """Return the deployment name, which is 'minio' for this storage type."""
        return "minio"

    # Minio is S3-compatible; a default region is often needed for S3 SDKs.
    MINIO_REGION = "us-east-1"

    def __init__(
        self,
        docker_client: docker.client,
        cache_client: Cache,
        resources: Resources, # Should be SelfHostedResources or similar if it holds MinioConfig
        replace_existing: bool,
    ):
        """
        Initialize the Minio storage client.

        :param docker_client: Docker client instance for managing the Minio container.
        :param cache_client: Cache client instance.
        :param resources: Cloud/system resources configuration object.
        :param replace_existing: Flag to control overwriting existing files.
        """
        super().__init__(self.MINIO_REGION, cache_client, resources, replace_existing)
        self._docker_client = docker_client
        self._storage_container: Optional[docker.models.containers.Container] = None # Type hint for container
        self._cfg = MinioConfig() # Default config, can be updated via property

    @property
    def config(self) -> MinioConfig:
        """The Minio specific configuration for this storage instance."""
        return self._cfg

    @config.setter
    def config(self, config: MinioConfig):
        """Set the Minio specific configuration."""
        self._cfg = config

    @staticmethod
    def _define_http_client(): # No type hint for urllib3.PoolManager as it's an import
        """
        Define a custom urllib3 HTTP client with specific timeout settings for Minio.

        This is used because the default Minio client might not offer sufficient
        timeout configuration directly. The settings are based on Minio's own client source.

        :return: A configured urllib3.PoolManager instance.
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

    def start(self):
        """
        Start the Minio Docker container.

        Configures a data volume for persistence, sets access/secret keys,
        and maps the container's port 9000 to a host port specified in `self._cfg.mapped_port`.
        The container ID and connection details are stored in `self._cfg`.

        :raises RuntimeError: If starting the Minio container fails.
        """
        if not self._cfg.data_volume: # Check if data_volume is empty or None
            minio_data_path = os.path.join(project_absolute_path(), "minio-volume")
        else:
            minio_data_path = self._cfg.data_volume
        minio_data_path = os.path.abspath(minio_data_path)
        else:
            minio_volume = self._cfg.data_volume
        minio_volume = os.path.abspath(minio_volume)

        os.makedirs(minio_volume, exist_ok=True)
        volumes = {
            minio_volume: {
                "bind": "/data",
                "mode": "rw",
            }
        }

        self._cfg.access_key = secrets.token_urlsafe(32)
        self._cfg.secret_key = secrets.token_hex(32)
        self._cfg.address = ""
        self.logging.info("Minio storage ACCESS_KEY={}".format(self._cfg.access_key))
        self.logging.info("Minio storage SECRET_KEY={}".format(self._cfg.secret_key))
        try:
            self.logging.info(f"Starting storage Minio on port {self._cfg.mapped_port}")
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

    def configure_connection(self):
        """
        Configure the connection details (address) for the Minio client.

        If the address is not already set in the config, it determines the
        Minio server address based on the Docker container's network settings.
        On Linux, it uses the container's bridge IP. On other systems (like
        Docker Desktop for Mac/Windows), it uses localhost with the mapped port.
        Initializes `self.connection` with a Minio client instance.

        :raises RuntimeError: If the Minio container is not running or IP address cannot be detected.
        """
        if not self._cfg.address: # Check if address is empty or None
            if self._storage_container is None:
                raise RuntimeError(
                    "Minio container is not available! Ensure Minio is started and configured."
                )
            self._storage_container.reload() # Refresh container attributes

            if is_linux(): # Native Linux Docker
                networks = self._storage_container.attrs.get("NetworkSettings", {}).get("Networks", {})
                bridge_network = networks.get("bridge", {})
                ip_address = bridge_network.get("IPAddress")
                if not ip_address:
                    # Fallback for some Docker versions or network modes if IPAddress is empty
                    ip_address = bridge_network.get("Gateway")
                if not ip_address:
                    self.logging.error(
                        "Could not determine Minio container IP address from bridge network. Attributes: %s",
                        json.dumps(self._storage_container.attrs, indent=2)
                    )
                    raise RuntimeError(f"Failed to detect IP address for Minio container {self._storage_container.id}")
                self._cfg.address = f"{ip_address}:9000" # Minio internal port is 9000
            else: # Docker Desktop (Windows, macOS), WSL
                # Mapped port from self._cfg should be used with localhost
                if self._cfg.mapped_port == -1:
                     raise RuntimeError("Minio host port not mapped or invalid for non-Linux Docker.")
                self._cfg.address = f"localhost:{self._cfg.mapped_port}"
            
            self.logging.info(f"Minio instance configured at {self._cfg.address}")
        
        self.connection = self.get_connection()

    def stop(self):
        """
        Stop the Minio Docker container if it's running.
        """
        if self._storage_container is not None:
            try:
                self.logging.info(f"Stopping Minio container {self._storage_container.id} at {self._cfg.address}.")
                self._storage_container.stop()
                self.logging.info(f"Stopped Minio container {self._storage_container.id}.")
            except docker.errors.NotFound:
                self.logging.warning(f"Minio container {self._storage_container.id} already removed or not found.")
            except docker.errors.APIError as e:
                self.logging.error(f"Error stopping Minio container {self._storage_container.id}: {e}")
        else:
            self.logging.warning("Attempted to stop Minio, but storage container instance is not known.")

    def get_connection(self) -> minio.Minio:
        """
        Create and return a Minio client connection instance.

        Uses connection details from `self._cfg` (address, access_key, secret_key).
        Configures a custom HTTP client with timeouts.

        :return: A `minio.Minio` client instance.
        """
        return minio.Minio(
            self._cfg.address,
            access_key=self._cfg.access_key, # Should be self._cfg.access_key
            secret_key=self._cfg.secret_key,
            secure=False,
            http_client=Minio._define_http_client(),
        )

    def _create_bucket(
        self, name: str, buckets: List[str] = [], randomize_name: bool = False
    ) -> str:
        """
        Create a Minio bucket.

        Checks if a bucket with a similar name prefix already exists in the `buckets` list.
        If `randomize_name` is True, appends a random string to the bucket name.
        Minio bucket names have a limit (often related to DNS compatibility, though Minio
        itself might be more flexible locally than S3). The original code mentioned a
        16-character limit for the random part, which implies overall length constraints.

        :param name: Desired base name for the bucket.
        :param buckets: List of existing bucket names to check against (prefix match).
        :param randomize_name: If True, append a random string to the bucket name.
        :return: Name of the created or existing bucket.
        :raises minio.error.S3Error: If bucket creation fails for other S3-compatible reasons.
        """
        # Check if a bucket with `name` as a prefix already exists
        for existing_bucket_name in buckets:
            if existing_bucket_name.startswith(name):
                self.logging.info(
                    f"Bucket {existing_bucket_name} (similar to {name}) already exists, skipping."
                )
                return existing_bucket_name

        bucket_to_create = name
        if randomize_name:
            # Minio bucket names are flexible but often adhere to S3/DNS for broader compatibility.
            # Using hyphen as separator and keeping it relatively short.
            random_suffix = str(uuid.uuid4())[0:8] # Shorter random part than original
            bucket_to_create = f"{name}-{random_suffix}"
        
        # Ensure name is valid for Minio (e.g. length, characters)
        # Minio itself is quite flexible, but S3 compatibility is often desired.
        # For simplicity, not adding complex validation here beyond what Minio client enforces.

        try:
            if not self.connection.bucket_exists(bucket_to_create):
                self.connection.make_bucket(bucket_to_create, location=self.MINIO_REGION)
                self.logging.info(f"Created Minio bucket {bucket_to_create}")
            else:
                self.logging.info(f"Minio bucket {bucket_to_create} already exists.")
            return bucket_to_create
        except (minio.error.S3Error) as err: # Catching general S3Error
            self.logging.error(f"Minio bucket creation/check for {bucket_to_create} failed: {err}")
            raise # Re-throw the Minio/S3 error

    def uploader_func(self, path_idx: int, file_key: str, local_filepath: str):
        """
        Upload a file to a Minio input bucket, used as a callback for multiprocessing.

        Constructs the object key using input prefixes. Skips upload if using cached
        buckets and not replacing existing files (though current check is basic).

        :param path_idx: Index of the input prefix from `self.input_prefixes`.
        :param file_key: Object key (filename) to use within the bucket, relative to prefix.
        :param local_filepath: Local path to the file to upload.
        :raises minio.error.S3Error: If upload fails.
        """
        # Note: Original did not check self.replace_existing or existing files here.
        # Adding a basic check, but proper cache handling would be more complex.
        if self.cached and not self.replace_existing:
            # A more robust check would be to list objects and see if this one exists.
            # For simplicity, this uploader assumes it should upload if called,
            # unless a more sophisticated check is added.
            self.logging.info(f"Skipping upload of {local_filepath} due to cache and no-replace policy (basic check).")
            return

        full_object_key = os.path.join(self.input_prefixes[path_idx], file_key)
        target_bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        try:
            self.logging.info(f"Uploading {local_filepath} to Minio bucket {target_bucket_name} as {full_object_key}")
            self.connection.fput_object(target_bucket_name, full_object_key, local_filepath)
        except minio.error.S3Error as err:
            self.logging.error(f"Minio upload of {local_filepath} failed: {err}")
            raise # Re-throw

    def clean(self):
        """
        Clean all output buckets associated with this Minio instance.

        Iterates through `self.output_prefixes` (which are path prefixes, not bucket names)
        and attempts to delete objects matching these prefixes from the EXPERIMENTS bucket.
        Note: This logic might need refinement if `output_prefixes` are not direct paths
        or if multiple output buckets are used per benchmark.
        """
        # Output prefixes are paths within the EXPERIMENTS bucket.
        experiments_bucket = self.get_bucket(Resources.StorageBucketType.EXPERIMENTS)
        if experiments_bucket:
            for prefix in self.output_prefixes:
                self.logging.info(f"Cleaning objects with prefix '{prefix}' from Minio bucket {experiments_bucket}")
                try:
                    objects_to_delete = self.connection.list_objects(experiments_bucket, prefix=prefix, recursive=True)
                    # minio.delete_objects needs a list of DeleteObject instances or just names
                    delete_obj_list = [minio.deleteobjects.DeleteObject(obj.object_name) for obj in objects_to_delete]
                    if delete_obj_list:
                        errors = self.connection.remove_objects(experiments_bucket, delete_obj_list)
                        for error in errors:
                            self.logging.error(f"Error deleting object from {experiments_bucket}: {error}")
                    else:
                        self.logging.info(f"No objects found with prefix '{prefix}' in {experiments_bucket} to clean.")
                except minio.error.S3Error as e:
                    self.logging.error(f"Error listing/cleaning objects in {experiments_bucket} with prefix {prefix}: {e}")
        else:
            self.logging.warning("No EXPERIMENTS bucket found to clean.")


    def download_results(self, result_dir_base: str): # Renamed arg for clarity
        """
        Download all objects from configured output prefixes to a local directory.

        Each output prefix (path in the EXPERIMENTS bucket) will correspond to a
        subdirectory within `result_dir_base/storage_output/`.

        :param result_dir_base: The base local directory to download results into.
                                A 'storage_output' subdirectory will be created here.
        """
        # Output prefixes are paths within the EXPERIMENTS bucket
        experiments_bucket = self.get_bucket(Resources.StorageBucketType.EXPERIMENTS)
        if not experiments_bucket:
            self.logging.warning("No EXPERIMENTS bucket found to download results from.")
            return

        storage_output_dir = os.path.join(result_dir_base, "storage_output")
        os.makedirs(storage_output_dir, exist_ok=True)

        for prefix in self.output_prefixes:
            self.logging.info(f"Downloading objects with prefix '{prefix}' from Minio bucket {experiments_bucket}")
            try:
                objects = self.connection.list_objects(experiments_bucket, prefix=prefix, recursive=True)
                for obj in objects:
                    # Create local path that mirrors the object's path relative to the prefix
                    relative_path = os.path.relpath(obj.object_name, prefix)
                    local_file_path = os.path.join(storage_output_dir, prefix, relative_path)
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    self.logging.debug(f"Downloading {obj.object_name} to {local_file_path}")
                    self.connection.fget_object(experiments_bucket, obj.object_name, local_file_path)
            except minio.error.S3Error as e:
                self.logging.error(f"Error downloading results from {experiments_bucket} with prefix {prefix}: {e}")


    def clean_bucket(self, bucket_name: str):
        """
        Delete all objects within a specified Minio bucket.

        :param bucket_name: Name of the Minio bucket to clean.
        """
        try:
            self.logging.info(f"Cleaning Minio bucket {bucket_name}")
            delete_object_list = [
                minio.deleteobjects.DeleteObject(obj.object_name)
                for obj in self.connection.list_objects(bucket_name, recursive=True)
            ]
            if delete_object_list:
                errors = self.connection.remove_objects(bucket_name, delete_object_list)
                for error in errors:
                    self.logging.error(f"Error deleting object from Minio bucket {bucket_name}: {error}")
            else:
                self.logging.info(f"Minio bucket {bucket_name} is already empty or has no objects to clean.")
        except minio.error.S3Error as e:
            self.logging.error(f"Error cleaning Minio bucket {bucket_name}: {e}")


    def remove_bucket(self, bucket_name: str): # Renamed arg for consistency
        """
        Delete a Minio bucket. The bucket must typically be empty.

        :param bucket_name: Name of the Minio bucket to delete.
        """
        try:
            self.logging.info(f"Removing Minio bucket {bucket_name}")
            self.connection.remove_bucket(bucket_name) # Minio remove_bucket expects bucket_name kwarg
            self.logging.info(f"Minio bucket {bucket_name} removed.")
        except minio.error.S3Error as e:
            self.logging.error(f"Error removing Minio bucket {bucket_name}: {e}")


    def correct_name(self, name: str) -> str:
        """
        Return the corrected bucket name (Minio is generally flexible, but S3
        compatibility rules might be desired). Currently returns name as is.

        :param name: Original bucket name.
        :return: Corrected bucket name.
        """
        # Minio bucket names are quite flexible. If strict S3 compatibility is needed,
        # more rules (lowercase, no underscores, 3-63 chars, etc.) would apply.
        # For local Minio, this is often not strictly enforced.
        return name

    def download(self, bucket_name: str, key: str, filepath: str): # Mark as -> None as per parent
        """
        Download an object from Minio. (Implementation provided by parent, this is override)

        :param bucket_name: Name of the bucket.
        :param key: Object key.
        :param filepath: Local path to save the file.
        :raises NotImplementedError: If not overridden by a concrete implementation (but it is).
        """
        # This method overrides the abstract one from PersistentStorage.
        # The actual implementation for fget_object is needed here if parent is truly abstract.
        # However, the original code structure seems to imply this *is* the implementation.
        # For clarity, if this is the direct Minio implementation:
        self.logging.info(f"Downloading {key} from Minio bucket {bucket_name} to {filepath}")
        try:
            self.connection.fget_object(bucket_name, key, filepath)
        except minio.error.S3Error as e:
            self.logging.error(f"Failed to download {key} from {bucket_name}: {e}")
            raise # Re-throw to indicate failure


    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if a Minio bucket exists.

        :param bucket_name: Name of the bucket.
        :return: True if the bucket exists, False otherwise.
        """
        return self.connection.bucket_exists(bucket_name)

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        List objects in a Minio bucket, optionally filtered by prefix.

        :param bucket_name: Name of the bucket.
        :param prefix: Optional prefix to filter objects.
        :return: List of object names.
        :raises RuntimeError: If the bucket does not exist.
        """
        try:
            # list_objects is recursive by default if prefix is used effectively.
            # To match S3-like behavior of non-recursive listing unless specified,
            # one might need to adjust or check Minio client specifics.
            # Assuming list_objects with a prefix gives objects *under* that prefix.
            objects_iterator = self.connection.list_objects(bucket_name, prefix=prefix, recursive=True)
            return [obj.object_name for obj in objects_iterator]
        except minio.error.S3Error as e: # Catching S3Error, which includes NoSuchBucket
            if "NoSuchBucket" in str(e): # More specific check if needed, though S3Error often suffices
                 raise RuntimeError(f"Attempting to list a non-existing Minio bucket: {bucket_name}") from e
            self.logging.error(f"Error listing Minio bucket {bucket_name}: {e}")
            raise # Re-throw other S3 errors

    def list_buckets(self, bucket_name_filter: Optional[str] = None) -> List[str]: # Renamed arg
        """
        List all Minio buckets, or filter by a partial name.

        :param bucket_name_filter: Optional string to filter bucket names (contains match).
        :return: List of bucket names.
        """
        buckets = self.connection.list_buckets()
        if bucket_name_filter is not None:
            return [bucket.name for bucket in buckets if bucket_name_filter in bucket.name]
        else:
            return [bucket.name for bucket in buckets]

    def upload(self, bucket_name: str, filepath: str, key: str): # Mark as -> None as per parent
        """
        Upload a file to Minio. (Implementation provided by parent, this is override)

        :param bucket_name: Name of the bucket.
        :param filepath: Local path of the file to upload.
        :param key: Object key for storage.
        :raises NotImplementedError: If not overridden (but it is).
        """
        # This method overrides the abstract one from PersistentStorage.
        self.logging.info(f"Uploading {filepath} to Minio bucket {bucket_name} as {key}")
        try:
            self.connection.fput_object(bucket_name, key, filepath)
        except minio.error.S3Error as e:
            self.logging.error(f"Failed to upload {filepath} to {bucket_name} as {key}: {e}")
            raise


    def serialize(self) -> dict:
        """
        Serialize the Minio storage configuration.

        :return: Dictionary representation of the MinioConfig.
        """
        return self._cfg.serialize()

    T = TypeVar("T", bound="Minio") # For type hinting the return of _deserialize

    @staticmethod
    def _deserialize(
        cached_config: MinioConfig,
        cache_client: Cache,
        resources: Resources, # Should be SelfHostedResources or similar
        obj_type: Type[T], # The concrete class type (Minio or subclass)
    ) -> T:
        """
        Internal helper to deserialize a Minio (or subclass) instance.

        Restores configuration and re-attaches to an existing Docker container if specified.
        This method supports creating instances of Minio or its subclasses, which is
        useful if Local/OpenWhisk storage types inherit from Minio but have their own class.

        :param cached_config: The MinioConfig object from cache/config.
        :param cache_client: Cache client instance.
        :param resources: The Resources object (expected to be SelfHostedResources compatible).
        :param obj_type: The actual class type to instantiate (Minio or a subclass).
        :return: An instance of `obj_type`.
        :raises RuntimeError: If a cached Docker container ID is provided but the container is not found.
        """
        docker_client = docker.from_env()
        # Create instance of the correct type (Minio or a subclass like LocalMinioStorage)
        obj = obj_type(docker_client, cache_client, resources, False) # False for replace_existing typically
        obj._cfg = cached_config # Apply the full MinioConfig

        if cached_config.instance_id: # If a container ID was cached
            try:
                obj._storage_container = docker_client.containers.get(cached_config.instance_id)
                obj.logging.info(f"Re-attached to existing Minio container {cached_config.instance_id}")
            except docker.errors.NotFound:
                obj.logging.error(f"Cached Minio container {cached_config.instance_id} not found!")
                # Decide on behavior: raise error, or try to start a new one?
                # Current SeBS logic might expect this to fail if container is gone.
                raise RuntimeError(f"Minio storage container {cached_config.instance_id} does not exist!")
            except docker.errors.APIError as e:
                obj.logging.error(f"API error attaching to Minio container {cached_config.instance_id}: {e}")
                raise
        else:
            obj._storage_container = None # No cached container ID

        # Restore prefixes from config, as they are part of MinioConfig now
        obj._input_prefixes = copy.copy(cached_config.input_buckets) # Assuming input_buckets are prefixes
        obj._output_prefixes = copy.copy(cached_config.output_buckets) # Assuming output_buckets are prefixes
        
        if obj._storage_container or obj._cfg.address : # If we have a container or a pre-configured address
            obj.configure_connection() # Setup Minio client connection
        
        return obj

    @staticmethod
    def deserialize(cached_config: MinioConfig, cache_client: Cache, res: Resources) -> "Minio":
        """
        Deserialize a Minio instance from a MinioConfig object.

        This is the primary public deserialization method for Minio.

        :param cached_config: The MinioConfig object (e.g., from a top-level config's resources).
        :param cache_client: Cache client instance.
        :param res: The Resources object.
        :return: A Minio instance.
        """
        return Minio._deserialize(cached_config, cache_client, res, Minio)

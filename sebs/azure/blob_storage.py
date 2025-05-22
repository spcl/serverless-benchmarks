import os
import uuid
from typing import List, Optional

from azure.storage.blob import BlobServiceClient

from sebs.cache import Cache
from sebs.faas.config import Resources
from ..faas.storage import PersistentStorage


class BlobStorage(PersistentStorage):
    """Azure Blob Storage persistent storage implementation."""
    @staticmethod
    def typename() -> str:
        """Return the type name of the storage implementation."""
        return "Azure.BlobStorage"

    @staticmethod
    def deployment_name():
        """Return the deployment name for Azure (azure)."""
        return "azure"

    def __init__(
        self,
        region: str,
        cache_client: Cache,
        resources: Resources,
        conn_string: str,
        replace_existing: bool,
    ):
        """
        Initialize Azure Blob Storage client.

        :param region: Azure region (used by parent class, not directly by BlobServiceClient).
        :param cache_client: Cache client instance.
        :param resources: Cloud resources configuration.
        :param conn_string: Azure Storage connection string.
        :param replace_existing: Flag to replace existing files in containers.
        """
        super().__init__(region, cache_client, resources, replace_existing)
        self.client: BlobServiceClient = BlobServiceClient.from_connection_string(conn_string)

    def _create_bucket(
        self, name: str, containers: List[str] = [], randomize_name: bool = False
    ) -> str:
        """
        Internal implementation of creating a new Azure Blob Storage container.

        Checks if a container with a similar name already exists.
        Randomizes name if requested.

        :param name: Desired base name for the container.
        :param containers: List of existing container names to check against.
        :param randomize_name: If True, append a random string to the container name.
        :return: Name of the created or existing container.
        """
        for c in containers:
            if name in c:
                self.logging.info("Container {} for {} already exists, skipping.".format(c, name))
                return c
        if randomize_name:
            random_name = str(uuid.uuid4())[0:16]
            name = "{}-{}".format(name, random_name)
        self.client.create_container(name)
        self.logging.info("Created container {}".format(name))
        return name

    def correct_name(self, name: str) -> str:
        """
        Correct a bucket/container name to comply with Azure Blob Storage naming rules.
        Azure does not allow dots in container names, so they are replaced with hyphens.

        :param name: Original bucket/container name.
        :return: Corrected name with dots replaced by hyphens.
        """
        return name.replace(".", "-")

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List Azure Blob Storage containers.

        Can filter by a starting prefix if `bucket_name` is provided.

        :param bucket_name: Optional prefix to filter container names.
        :return: List of container names.
        """
        if bucket_name is not None:
            return [
                container["name"]
                for container in self.client.list_containers(name_starts_with=bucket_name)
            ]
        else:
            return [container["name"] for container in self.client.list_containers()]

    def uploader_func(self, container_idx: int, file: str, filepath: str):
        """
        Upload a file to an Azure Blob Storage container, used as a callback.

        Skips upload if using cached containers and not replacing existing files.
        Constructs the blob key using input prefixes.

        :param container_idx: Index of the input path/prefix.
        :param file: Blob name (filename) within the container.
        :param filepath: Local path to the file to upload.
        """
        # Skip upload when using cached containers
        if self.cached and not self.replace_existing:
            return

        container_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        key = os.path.join(self.input_prefixes[container_idx], file)
        if not self.replace_existing:
            for f in self.input_prefixes_files[container_idx]:
                if f == file:
                    self.logging.info(
                        "Skipping upload of {} to {}".format(filepath, container_name)
                    )
                    return
        client = self.client.get_blob_client(container_name, key)
        with open(filepath, "rb") as file_data:
            client.upload_blob(data=file_data, overwrite=True)
        self.logging.info("Upload {} to {}".format(filepath, container_name))

    def download(self, container_name: str, key: str, filepath: str):
        """
        Download a blob from an Azure Blob Storage container to a local file.

        :param container_name: Name of the Azure Blob Storage container.
        :param key: Blob key (path within the container).
        :param filepath: Local path to save the downloaded file.
        """
        self.logging.info("Download {}:{} to {}".format(container_name, key, filepath))
        client = self.client.get_blob_client(container_name, key)
        with open(filepath, "wb") as download_file:
            download_file.write(client.download_blob().readall())

    def upload(self, container_name: str, filepath: str, key: str):
        """
        Upload a file to a specified Azure Blob Storage container.

        :param container_name: Name of the Azure Blob Storage container.
        :param filepath: Local path to the file.
        :param key: Blob key (path within the container).
        """
        self.logging.info("Upload {} to {}".format(filepath, container_name))
        client = self.client.get_blob_client(container_name, key)
        with open(filepath, "rb") as upload_file:
            client.upload_blob(upload_file, overwrite=True) # type: ignore

    def exists_bucket(self, container: str) -> bool:
        """
        Check if an Azure Blob Storage container exists.

        :param container: Name of the container.
        :return: True if the container exists, False otherwise.
        """
        return self.client.get_container_client(container).exists()

    def list_bucket(self, container: str, prefix: str = "") -> List[str]:
        """
        Return list of blobs in an Azure Blob Storage container.

        Can filter by a prefix.

        :param container: Name of the container.
        :param prefix: Optional prefix to filter blob names.
        :return: List of blob names. Empty if container is empty or no blobs match the prefix.
        """
        objects = list(
            map(
                lambda x: x["name"],
                self.client.get_container_client(container).list_blobs(name_starts_with=prefix),
            )
        )
        # The list_blobs with name_starts_with already filters by prefix at the API level.
        # The original list comprehension `[x for x in objects if prefix in x]`
        # would do a substring match which might not be the intended behavior
        # if prefix is meant to be a path prefix.
        # Assuming name_starts_with is sufficient.
        return objects

    def clean_bucket(self, bucket: str):
        """
        Delete all blobs within an Azure Blob Storage container.

        :param bucket: Name of the container to clean.
        """
        self.logging.info("Clean output container {}".format(bucket))
        container_client = self.client.get_container_client(bucket)
        blobs_to_delete = [blob["name"] for blob in container_client.list_blobs()]
        if blobs_to_delete:
            container_client.delete_blobs(*blobs_to_delete)

    def remove_bucket(self, bucket: str):
        """
        Delete an Azure Blob Storage container. The container must be empty or cleaning should be handled.

        :param bucket: Name of the container to delete.
        """
        self.client.get_container_client(bucket).delete_container()

"""Azure Blob Storage implementation for SeBS benchmarking.

This module provides Azure Blob Storage integration for the SeBS benchmarking
suite. It handles container management, file uploads/downloads, and storage
operations required for serverless function benchmarking.

The BlobStorage class implements the PersistentStorage interface to provide
Azure-specific storage operations including container creation, file management,
and cleanup operations.

Example:
    Basic usage for Azure Blob Storage:
    
    ```python
    from sebs.azure.blob_storage import BlobStorage
    
    # Initialize with connection string
    storage = BlobStorage(region, cache, resources, connection_string, False)
    
    # Upload benchmark data
    storage.upload(container_name, filepath, key)
    
    # Download results
    storage.download(container_name, key, local_filepath)
    ```
"""

import os
import uuid
from typing import List, Optional

from azure.storage.blob import BlobServiceClient

from sebs.cache import Cache
from sebs.faas.config import Resources
from ..faas.storage import PersistentStorage


class BlobStorage(PersistentStorage):
    """Azure Blob Storage implementation for benchmark data management.
    
    This class provides Azure Blob Storage operations for storing and retrieving
    benchmark input data, function outputs, and temporary files. It manages
    containers (equivalent to S3 buckets) and handles file operations with
    proper error handling and logging.
    
    Attributes:
        client: Azure Blob Service client for storage operations
    """
    
    @staticmethod
    def typename() -> str:
        """Get the storage type name.
        
        Returns:
            Storage type identifier for Azure Blob Storage.
        """
        return "Azure.BlobStorage"

    @staticmethod
    def deployment_name() -> str:
        """Get the deployment platform name.
        
        Returns:
            Platform name 'azure'.
        """
        return "azure"

    def __init__(
        self,
        region: str,
        cache_client: Cache,
        resources: Resources,
        conn_string: str,
        replace_existing: bool,
    ) -> None:
        """Initialize Azure Blob Storage.
        
        Args:
            region: Azure region for storage operations
            cache_client: Cache for storing storage configuration
            resources: Resources configuration
            conn_string: Azure Storage connection string
            replace_existing: Whether to replace existing files
        """
        super().__init__(region, cache_client, resources, replace_existing)
        self.client: BlobServiceClient = BlobServiceClient.from_connection_string(conn_string)

    def _create_bucket(
        self, name: str, containers: List[str] = [], randomize_name: bool = False
    ) -> str:
        """Create new Azure Blob Storage container.
        
        Internal implementation for creating containers with optional
        name randomization and existence checking.
        
        Args:
            name: Base name for the container
            containers: List of existing containers to check
            randomize_name: Whether to append random suffix to name
            
        Returns:
            Name of the created or existing container.
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
        """Correct container name for Azure requirements.
        
        Azure Blob Storage does not allow dots in container names,
        so they are replaced with hyphens.
        
        Args:
            name: Original container name
            
        Returns:
            Corrected container name with dots replaced by hyphens.
        """
        return name.replace(".", "-")

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """List Azure Blob Storage containers.
        
        Lists all containers or those matching a prefix.
        
        Args:
            bucket_name: Optional prefix to filter container names
            
        Returns:
            List of container names.
        """
        if bucket_name is not None:
            return [
                container["name"]
                for container in self.client.list_containers(name_starts_with=bucket_name)
            ]
        else:
            return [container["name"] for container in self.client.list_containers()]

    def uploader_func(self, container_idx: int, file: str, filepath: str) -> None:
        """Upload file to Azure Blob Storage container.
        
        Uploads a file to the specified container with proper path handling
        and duplicate checking.
        
        Args:
            container_idx: Index of the container for file organization
            file: Name of the file being uploaded
            filepath: Local path to the file to upload
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

    def download(self, container_name: str, key: str, filepath: str) -> None:
        """Download file from Azure Blob Storage.
        
        Downloads a blob from the specified container to a local file.
        
        Args:
            container_name: Name of the Azure Blob Storage container
            key: Blob key/name in the container
            filepath: Local file path to save the downloaded content
        """
        self.logging.info("Download {}:{} to {}".format(container_name, key, filepath))
        client = self.client.get_blob_client(container_name, key)
        with open(filepath, "wb") as download_file:
            download_file.write(client.download_blob().readall())

    def upload(self, container_name: str, filepath: str, key: str) -> None:
        """Upload file to Azure Blob Storage.
        
        Uploads a local file to the specified container with the given key.
        
        Args:
            container_name: Name of the Azure Blob Storage container
            filepath: Local file path to upload
            key: Blob key/name in the container
        """
        self.logging.info("Upload {} to {}".format(filepath, container_name))
        client = self.client.get_blob_client(container_name, key)
        with open(filepath, "rb") as upload_file:
            client.upload_blob(upload_file)  # type: ignore

    def exists_bucket(self, container: str) -> bool:
        """Check if Azure Blob Storage container exists.
        
        Args:
            container: Name of the container to check
            
        Returns:
            True if container exists, False otherwise.
        """
        return self.client.get_container_client(container).exists()

    def list_bucket(self, container: str, prefix: str = "") -> List[str]:
        """List files in Azure Blob Storage container.
        
        Returns list of blob names in the specified container,
        optionally filtered by prefix.
        
        Args:
            container: Name of the container to list
            prefix: Optional prefix to filter blob names
            
        Returns:
            List of blob names. Empty list if container is empty.
        """
        objects = list(
            map(
                lambda x: x["name"],
                self.client.get_container_client(container).list_blobs(),
            )
        )
        return [x for x in objects if prefix in x]

    def clean_bucket(self, bucket: str) -> None:
        """Clean all blobs from Azure Blob Storage container.
        
        Removes all blobs from the specified container but keeps
        the container itself.
        
        Args:
            bucket: Name of the container to clean
        """
        self.logging.info("Clean output container {}".format(bucket))
        container_client = self.client.get_container_client(bucket)
        blobs = list(map(lambda x: x["name"], container_client.list_blobs()))
        if len(blobs) > 0:
            container_client.delete_blobs(*blobs)

    def remove_bucket(self, bucket: str) -> None:
        """Remove Azure Blob Storage container.
        
        Deletes the entire container and all its contents.
        
        Args:
            bucket: Name of the container to remove
        """
        self.client.get_container_client(bucket).delete_container()

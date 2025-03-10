"""
Module for NoSQL database storage abstraction in the Serverless Benchmarking Suite.

This module provides an abstract base class for NoSQL database implementations
across different cloud platforms (AWS DynamoDB, Azure CosmosDB, Google Cloud Datastore)
and local development environments. It handles table creation, data writing, and
cache management for benchmark data stored in NoSQL databases.
"""

from abc import ABC
from abc import abstractmethod
from typing import Dict, Optional, Tuple

from sebs.faas.config import Resources
from sebs.cache import Cache
from sebs.utils import LoggingBase


class NoSQLStorage(ABC, LoggingBase):
    """
    Abstract base class for NoSQL database storage implementations.
    
    This class defines the interface for NoSQL database operations across different
    cloud platforms and local environments. Concrete implementations handle the
    platform-specific details of creating tables, writing data, and managing
    resources.
    
    Attributes:
        cache_client: Client for caching database information
        region: Cloud region where the database is deployed
    """
    
    @staticmethod
    @abstractmethod
    def deployment_name() -> str:
        """
        Get the name of the deployment platform.
        
        Returns:
            str: Name of the deployment platform (e.g., 'aws', 'azure', 'gcp')
        """
        pass

    @property
    def cache_client(self) -> Cache:
        """
        Get the cache client.
        
        Returns:
            Cache: The cache client for database information
        """
        return self._cache_client

    @property
    def region(self) -> str:
        """
        Get the cloud region.
        
        Returns:
            str: The cloud region where the database is deployed
        """
        return self._region

    def __init__(self, region: str, cache_client: Cache, resources: Resources):
        """
        Initialize a NoSQL storage instance.
        
        Args:
            region: Cloud region where the database is deployed
            cache_client: Client for caching database information
            resources: Resource configuration for the database
        """
        super().__init__()
        self._cache_client = cache_client
        self._cached = False
        self._region = region
        self._cloud_resources = resources

    @abstractmethod
    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get all tables associated with a benchmark.
        
        Args:
            benchmark: Name of the benchmark
            
        Returns:
            Dict[str, str]: Dictionary mapping table logical names to physical table names
        """
        pass

    @abstractmethod
    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the physical table name for a benchmark's logical table.
        
        Args:
            benchmark: Name of the benchmark
            table: Logical name of the table
            
        Returns:
            Optional[str]: Physical table name if it exists, None otherwise
        """
        pass

    @abstractmethod
    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve cached table information for a benchmark.
        
        Args:
            benchmark: Name of the benchmark
            
        Returns:
            bool: True if cache was successfully retrieved, False otherwise
        """
        pass

    @abstractmethod
    def update_cache(self, benchmark: str):
        """
        Update the cache with the latest table information for a benchmark.
        
        Args:
            benchmark: Name of the benchmark
        """
        pass

    def envs(self) -> dict:
        """
        Get environment variables required for connecting to the NoSQL storage.
        
        Returns:
            dict: Dictionary of environment variables
        """
        return {}

    """
    Table naming convention and implementation requirements.
    
    Each table name follows this pattern:
    sebs-benchmarks-{resource_id}-{benchmark-name}-{table-name}

    Each implementation should do the following:
    1. Retrieve cached data
    2. Create missing tables that do not exist
    3. Update cached data if anything new was created (done separately
       in benchmark.py once the data is uploaded by the benchmark)
    """

    def create_benchmark_tables(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ):
        """
        Create a table for a benchmark if it doesn't exist in the cache.
        
        Checks if the table already exists in the cache. If not, creates a new table
        with the specified keys.
        
        Args:
            benchmark: Name of the benchmark
            name: Logical name of the table
            primary_key: Primary key field name
            secondary_key: Optional secondary key field name
        """
        if self.retrieve_cache(benchmark):
            table_name = self._get_table_name(benchmark, name)
            if table_name is not None:
                self.logging.info(
                    f"Using cached NoSQL table {table_name} for benchmark {benchmark}"
                )
                return

        self.logging.info(f"Preparing to create a NoSQL table {name} for benchmark {benchmark}")
        self.create_table(benchmark, name, primary_key, secondary_key)

    """
    Platform-specific table implementations:
    
    - AWS: DynamoDB Table
    - Azure: CosmosDB Container
    - Google Cloud: Firestore in Datastore Mode, Database
    """

    @abstractmethod
    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        """
        Create a new table for a benchmark.
        
        Args:
            benchmark: Name of the benchmark
            name: Logical name of the table
            primary_key: Primary key field name
            secondary_key: Optional secondary key field name
            
        Returns:
            str: Physical name of the created table
        """
        pass

    @abstractmethod
    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ):
        """
        Write data to a table.
        
        Args:
            benchmark: Name of the benchmark
            table: Logical name of the table
            data: Dictionary of data to write
            primary_key: Tuple of (key_name, key_value) for the primary key
            secondary_key: Optional tuple of (key_name, key_value) for the secondary key
        """
        pass

    """
    Table management operations:
    
    - AWS DynamoDB: Removing & recreating table is the cheapest & fastest option
    - Azure CosmosDB: Recreate container
    - Google Cloud: Also likely recreate
    """

    @abstractmethod
    def clear_table(self, name: str) -> str:
        """
        Clear all data from a table.
        
        Args:
            name: Name of the table to clear
            
        Returns:
            str: Result message or status
        """
        pass

    @abstractmethod
    def remove_table(self, name: str) -> str:
        """
        Remove a table completely.
        
        Args:
            name: Name of the table to remove
            
        Returns:
            str: Result message or status
        """
        pass

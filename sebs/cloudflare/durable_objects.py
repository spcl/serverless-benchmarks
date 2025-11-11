import json
import requests
from typing import Dict, Optional, Tuple

from sebs.cloudflare.config import CloudflareCredentials
from sebs.faas.nosql import NoSQLStorage
from sebs.faas.config import Resources
from sebs.cache import Cache


class DurableObjects(NoSQLStorage):
    """
    Cloudflare Durable Objects implementation for NoSQL storage.
    
    Note: Durable Objects are not a traditional NoSQL database like DynamoDB or CosmosDB.
    They are stateful Workers with persistent storage. This implementation provides
    a minimal interface to satisfy SeBS requirements, but full table operations
    are not supported.
    """

    @staticmethod
    def typename() -> str:
        return "Cloudflare.DurableObjects"

    @staticmethod
    def deployment_name() -> str:
        return "cloudflare"

    def __init__(
        self,
        region: str,
        cache_client: Cache,
        resources: Resources,
        credentials: CloudflareCredentials,
    ):
        super().__init__(region, cache_client, resources)
        self._credentials = credentials
        self._tables: Dict[str, str] = {}

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for Cloudflare API requests."""
        if self._credentials.api_token:
            return {
                "Authorization": f"Bearer {self._credentials.api_token}",
                "Content-Type": "application/json",
            }
        elif self._credentials.email and self._credentials.api_key:
            return {
                "X-Auth-Email": self._credentials.email,
                "X-Auth-Key": self._credentials.api_key,
                "Content-Type": "application/json",
            }
        else:
            raise RuntimeError("Invalid Cloudflare credentials configuration")

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        """
        Get all tables for a benchmark.
        
        :param benchmark: benchmark name
        :return: dictionary mapping table names to their IDs
        """
        # For Durable Objects, we don't have traditional tables
        # Return cached tables if any
        return self._tables.copy()

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the full table name for a benchmark table.
        
        :param benchmark: benchmark name
        :param table: table name
        :return: full table name or None if not found
        """
        key = f"{benchmark}:{table}"
        return self._tables.get(key)

    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve cached table information.
        
        :param benchmark: benchmark name
        :return: True if cache was found and loaded
        """
        cache_key = f"cloudflare.durable_objects.{benchmark}"
        cached = self.cache_client.get(cache_key)
        
        if cached:
            self._tables.update(cached)
            self.logging.info(f"Retrieved cached Durable Objects tables for {benchmark}")
            return True
        
        return False

    def update_cache(self, benchmark: str):
        """
        Update cache with current table information.
        
        :param benchmark: benchmark name
        """
        cache_key = f"cloudflare.durable_objects.{benchmark}"
        
        # Filter tables for this benchmark
        benchmark_tables = {
            k: v for k, v in self._tables.items() if k.startswith(f"{benchmark}:")
        }
        
        self.cache_client.update(cache_key, benchmark_tables)
        self.logging.info(f"Updated cache for Durable Objects tables for {benchmark}")

    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        """
        Create a table (Durable Object namespace).
        
        Note: Durable Objects don't have traditional table creation via API.
        They are defined in the Worker code and wrangler.toml.
        This method just tracks the table name.
        
        :param benchmark: benchmark name
        :param name: table name
        :param primary_key: primary key field name
        :param secondary_key: optional secondary key field name
        :return: table name
        """
        resource_id = self._cloud_resources.get_resource_id()
        table_name = f"sebs-benchmarks-{resource_id}-{benchmark}-{name}"
        
        key = f"{benchmark}:{name}"
        self._tables[key] = table_name
        
        self.logging.info(
            f"Registered Durable Objects table {table_name} for benchmark {benchmark}"
        )
        
        return table_name

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ):
        """
        Write data to a table (Durable Object).
        
        Note: This would require HTTP requests to the Durable Object endpoints.
        For now, this is not fully implemented.
        
        :param benchmark: benchmark name
        :param table: table name
        :param data: data to write
        :param primary_key: primary key (field_name, value)
        :param secondary_key: optional secondary key (field_name, value)
        """
        table_name = self._get_table_name(benchmark, table)
        
        if not table_name:
            raise ValueError(f"Table {table} not found for benchmark {benchmark}")
        
        self.logging.warning(
            f"write_to_table not fully implemented for Durable Objects table {table_name}"
        )

    def clear_table(self, name: str) -> str:
        """
        Clear all data from a table.
        
        :param name: table name
        :return: table name
        """
        self.logging.warning(f"clear_table not fully implemented for Durable Objects table {name}")
        return name

    def remove_table(self, name: str) -> str:
        """
        Remove a table.
        
        :param name: table name
        :return: table name
        """
        # Remove from internal tracking
        keys_to_remove = [k for k, v in self._tables.items() if v == name]
        for key in keys_to_remove:
            del self._tables[key]
        
        self.logging.info(f"Removed Durable Objects table {name} from tracking")
        return name

    def envs(self) -> dict:
        """
        Get environment variables for accessing Durable Objects.
        
        :return: dictionary of environment variables
        """
        # Durable Objects are accessed via bindings in the Worker
        # No additional environment variables needed
        return {}

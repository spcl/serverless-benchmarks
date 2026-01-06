import json
from collections import defaultdict
from typing import Dict, Optional, Tuple

from sebs.cloudflare.config import CloudflareCredentials
from sebs.faas.nosql import NoSQLStorage
from sebs.faas.config import Resources
from sebs.cache import Cache


class DurableObjects(NoSQLStorage):
    """
    Cloudflare Durable Objects implementation for NoSQL storage.
    
    Note: Durable Objects are not managed via API like DynamoDB or CosmosDB.
    Instead, they are defined in the Worker code and wrangler.toml, and accessed
    via bindings in the Worker environment. This implementation provides a minimal
    interface to satisfy SeBS requirements by tracking table names without actual
    API-based table creation.
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
        # Tables are just logical names - Durable Objects are accessed via Worker bindings
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)

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
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        """
        Get the full table name for a benchmark table.
        
        :param benchmark: benchmark name
        :param table: table name
        :return: full table name or None if not found
        """
        if benchmark not in self._tables:
            return None

        if table not in self._tables[benchmark]:
            return None

        return self._tables[benchmark][table]

    def retrieve_cache(self, benchmark: str) -> bool:
        """
        Retrieve cached table information.
        
        :param benchmark: benchmark name
        :return: True if cache was found and loaded
        """
        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is not None:
            self._tables[benchmark] = cached_storage["tables"]
            self.logging.info(f"Retrieved cached Durable Objects tables for {benchmark}")
            return True
        
        return False

    def update_cache(self, benchmark: str):
        """
        Update cache with current table information.
        
        :param benchmark: benchmark name
        """
        self.cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {
                "tables": self._tables[benchmark],
            },
        )
        self.logging.info(f"Updated cache for Durable Objects tables for {benchmark}")

    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        """
        Register a table name for a benchmark.
        
        Note: Durable Objects don't have traditional table creation via API.
        They are defined in the Worker code and wrangler.toml, and accessed via
        bindings. This method just tracks the logical table name for the wrapper
        to use when accessing the Durable Object binding.
        
        :param benchmark: benchmark name
        :param name: table name
        :param primary_key: primary key field name
        :param secondary_key: optional secondary key field name
        :return: table name (same as input name - used directly as binding name)
        """
        # For Cloudflare, table names are used directly as the binding names
        # in the wrapper code, so we just use the simple name
        self._tables[benchmark][name] = name
        
        self.logging.info(
            f"Registered Durable Object table '{name}' for benchmark {benchmark}"
        )
        
        return name

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
        
        Note: Cloudflare Durable Objects can only be written to from within the Worker,
        not via external API calls. Data seeding for benchmarks is not supported.
        Benchmarks that require pre-populated data (like test/small sizes of crud-api)
        will return empty results. Use 'large' size which creates its own data.
        
        :param benchmark: benchmark name
        :param table: table name
        :param data: data to write
        :param primary_key: primary key (field_name, value)
        :param secondary_key: optional secondary key (field_name, value)
        """
        table_name = self._get_table_name(benchmark, table)
        
        if not table_name:
            raise ValueError(f"Table {table} not found for benchmark {benchmark}")
        
        # Silently skip data seeding for Cloudflare Durable Objects
        # This is a platform limitation
        pass

    def clear_table(self, name: str) -> str:
        """
        Clear all data from a table.
        
        Note: Durable Object data is managed within the Worker.
        
        :param name: table name
        :return: table name
        """
        self.logging.info(f"Durable Objects data is managed within the Worker")
        return name

    def remove_table(self, name: str) -> str:
        """
        Remove a table from tracking.
        
        :param name: table name
        :return: table name
        """
        # Remove from internal tracking - two-step approach to avoid mutation during iteration
        benchmark_to_modify = None
        table_key_to_delete = None
        
        # Step 1: Find the benchmark and table_key without deleting
        for benchmark, tables in list(self._tables.items()):
            if name in tables.values():
                # Find the table key
                for table_key, table_name in list(tables.items()):
                    if table_name == name:
                        benchmark_to_modify = benchmark
                        table_key_to_delete = table_key
                        break
                break
        
        # Step 2: Perform deletion after iteration
        if benchmark_to_modify is not None and table_key_to_delete is not None:
            del self._tables[benchmark_to_modify][table_key_to_delete]
        
        self.logging.info(f"Removed Durable Objects table {name} from tracking")
        return name

    def envs(self) -> dict:
        """
        Get environment variables for accessing Durable Objects.
        
        Durable Objects are accessed via bindings in the Worker environment,
        which are configured in wrangler.toml. We set a marker environment
        variable so the wrapper knows Durable Objects are available.
        
        :return: dictionary of environment variables
        """
        # Set a marker that Durable Objects are enabled
        # The actual bindings (DURABLE_STORE, etc.) are configured in wrangler.toml
        return {
            "NOSQL_STORAGE_DATABASE": "durable_objects"
        }

import hashlib
import json
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from sebs.cache import Cache
from sebs.cloudflare.config import CloudflareCredentials
from sebs.faas.config import Resources
from sebs.faas.nosql import NoSQLStorage


class KVStore(NoSQLStorage):
    """
    Cloudflare KV-backed NoSQL storage for SeBS.

    Cloudflare KV is a flat key-value store: there are no tables, schemas, or
    secondary indexes. The SeBS NoSQL abstraction (modelled after DynamoDB /
    Cosmos DB / Datastore) is therefore layered on top of KV as follows.

    Table -> namespace mapping
    --------------------------
    Each (benchmark, logical table) pair is mapped to exactly one KV namespace
    -- the coarsest isolation unit KV offers. Namespaces are titled

        sebs-nosql-<resource_id>-<benchmark>-<table>

    with each component sanitized to ``[A-Za-z0-9_-]`` and a SHA1 suffix
    appended when the title would exceed Cloudflare's 100-character limit
    (see ``_namespace_title``). A one-namespace-per-table layout is used
    instead of packing multiple tables into a shared namespace because:

    * Workers bind namespaces by id, so one binding per table is the natural
      way to expose the logical table to the benchmark code.
    * ``cleanup_tables`` / ``remove_table`` can drop a whole table by deleting
      its namespace -- KV has no bulk-delete-by-prefix primitive.
    * Key collisions between benchmarks or logical tables are impossible.

    Key mapping
    -----------
    Items are stored as JSON values under composite keys:

        <primary_key_value>#<secondary_key_value>    (when a secondary key exists)
        <primary_key_value>                          (otherwise)

    The primary and secondary key fields are also written back into the JSON
    value so that clients reading an item do not have to re-parse the key.

    Secondary-key indices
    ---------------------
    KV exposes a ``list`` API, but from inside a Worker it is paginated,
    eventually consistent, and scales with the total namespace size -- not
    with the number of items under a given primary key. DynamoDB-style query
    patterns ("give me every item with primary key = X") would therefore be
    prohibitively expensive if implemented via ``list``.

    To support those queries with point reads only, ``write_to_table``
    additionally maintains a per-primary-key index entry:

        __sebs_idx__<primary_key_value> -> JSON array of secondary-key values

    A query then becomes one ``GET`` for the index followed by one ``GET`` per
    secondary value. The index is only written when a secondary key is
    supplied; tables without a secondary key do not need it. The matching
    read path lives in ``benchmarks/wrappers/cloudflare/*/nosql.*``.
    """

    NAMESPACE_ID_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")

    @staticmethod
    def typename() -> str:
        return "Cloudflare.KVStore"

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
        # benchmark -> logical table name -> KV namespace id
        self._tables: Dict[str, Dict[str, str]] = defaultdict(dict)

    def _account_id(self) -> str:
        account_id = self._credentials.account_id
        if not account_id:
            raise RuntimeError("Cloudflare account ID is required for KV operations")
        return account_id

    def _kv_api_base(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self._account_id()}/storage/kv/namespaces"

    def _get_auth_headers(self, content_type: str = "application/json") -> dict[str, str]:
        """Get authentication headers for Cloudflare API requests."""
        if self._credentials.api_token:
            return {
                "Authorization": f"Bearer {self._credentials.api_token}",
                "Content-Type": content_type,
            }
        elif self._credentials.email and self._credentials.api_key:
            return {
                "X-Auth-Email": self._credentials.email,
                "X-Auth-Key": self._credentials.api_key,
                "Content-Type": content_type,
            }
        else:
            raise RuntimeError("Invalid Cloudflare credentials configuration")

    @classmethod
    def _is_namespace_id(cls, value: str) -> bool:
        return bool(cls.NAMESPACE_ID_PATTERN.fullmatch(value))

    def _resource_id(self) -> str:
        if self._cloud_resources.has_resources_id:
            return self._cloud_resources.resources_id
        return "default"

    @staticmethod
    def _sanitize_component(value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "-", value)
        return sanitized.strip("-") or "default"

    def _namespace_title(self, benchmark: str, table: str) -> str:
        title = (
            f"sebs-nosql-{self._sanitize_component(self._resource_id())}-"
            f"{self._sanitize_component(benchmark)}-{self._sanitize_component(table)}"
        )
        # Cloudflare KV namespace title has length constraints. Keep a deterministic suffix if truncated.
        max_len = 100
        if len(title) > max_len:
            digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
            title = f"{title[: max_len - 13]}-{digest}"
        return title

    def _list_namespaces(self) -> List[dict]:
        namespaces: List[dict] = []
        page = 1
        per_page = 100

        while True:
            response = requests.get(
                self._kv_api_base(),
                params={"page": page, "per_page": per_page},
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            payload = response.json()

            if not payload.get("success"):
                raise RuntimeError(f"Failed to list KV namespaces: {payload.get('errors')}")

            page_items = payload.get("result", [])
            namespaces.extend(page_items)

            page_info = payload.get("result_info", {}) or {}
            total_pages = int(page_info.get("total_pages", 1))
            if page >= total_pages:
                break
            page += 1

        return namespaces

    def _find_namespace_id_by_title(self, title: str) -> Optional[str]:
        for namespace in self._list_namespaces():
            if namespace.get("title") == title:
                return namespace.get("id")
        return None

    def _delete_namespace(self, namespace_id: str) -> None:
        response = requests.delete(
            f"{self._kv_api_base()}/{namespace_id}",
            headers=self._get_auth_headers(),
        )
        if response.status_code == 404:
            return
        response.raise_for_status()

        if response.content:
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(
                    f"Failed to delete KV namespace {namespace_id}: {payload.get('errors')}"
                )

    @staticmethod
    def _compose_key(
        primary_key: Tuple[str, str], secondary_key: Optional[Tuple[str, str]] = None
    ) -> str:
        if secondary_key is None:
            return str(primary_key[1])
        return f"{primary_key[1]}#{secondary_key[1]}"

    @staticmethod
    def _index_key(primary_value: str) -> str:
        return f"__sebs_idx__{primary_value}"

    def _read_index(self, namespace_id: str, primary_value: str) -> List[str]:
        response = requests.get(
            f"{self._kv_api_base()}/{namespace_id}/values/{quote(self._index_key(primary_value), safe='')}",
            headers=self._get_auth_headers(),
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()

        raw = response.text
        if not raw:
            return []

        try:
            parsed = json.loads(raw)
        except Exception:
            return []

        if not isinstance(parsed, list):
            return []

        return [str(v) for v in parsed]

    def _write_index(self, namespace_id: str, primary_value: str, values: List[str]) -> None:
        response = requests.put(
            f"{self._kv_api_base()}/{namespace_id}/values/{quote(self._index_key(primary_value), safe='')}",
            data=json.dumps(values, separators=(",", ":")).encode("utf-8"),
            headers=self._get_auth_headers(content_type="text/plain;charset=UTF-8"),
        )
        response.raise_for_status()

    def _get_tables(self) -> Dict[str, List[str]]:
        tables = self.cache_client.get_nosql_configs(self.deployment_name())
        return {benchmark: list(v.values()) for benchmark, v in tables.items()}

    def get_tables(self, benchmark: str) -> Dict[str, str]:
        return self._tables[benchmark]

    def _get_table_name(self, benchmark: str, table: str) -> Optional[str]:
        if benchmark not in self._tables:
            return None
        if table not in self._tables[benchmark]:
            return None
        return self._tables[benchmark][table]

    def retrieve_cache(self, benchmark: str) -> bool:
        if benchmark in self._tables:
            return True

        cached_storage = self.cache_client.get_nosql_config(self.deployment_name(), benchmark)
        if cached_storage is None:
            return False

        cached_tables = cached_storage.get("tables", {})
        if not isinstance(cached_tables, dict):
            return False

        # Ignore legacy Durable Objects cache entries (table -> table name).
        if cached_tables and not all(
            isinstance(v, str) and self._is_namespace_id(v) for v in cached_tables.values()
        ):
            self.logging.warning(
                f"Ignoring legacy/non-KV cache for benchmark {benchmark}; creating KV namespaces."
            )
            return False

        self._tables[benchmark] = cached_tables
        self.logging.info(f"Retrieved cached KV namespace mappings for {benchmark}")
        return True

    def update_cache(self, benchmark: str):
        self.cache_client.update_nosql(
            self.deployment_name(),
            benchmark,
            {"tables": self._tables[benchmark]},
        )
        self.logging.info(f"Updated cache for KV namespace mappings for {benchmark}")

    def create_table(
        self, benchmark: str, name: str, primary_key: str, secondary_key: Optional[str] = None
    ) -> str:
        # Unused in KV namespace allocation, kept for interface compatibility
        _ = primary_key, secondary_key

        existing = self._get_table_name(benchmark, name)
        if existing:
            return existing

        namespace_title = self._namespace_title(benchmark, name)

        existing_namespace_id = self._find_namespace_id_by_title(namespace_title)
        if existing_namespace_id:
            self._tables[benchmark][name] = existing_namespace_id
            self.logging.info(
                f"Reusing existing KV namespace '{namespace_title}' ({existing_namespace_id})"
            )
            return existing_namespace_id

        response = requests.post(
            self._kv_api_base(),
            json={"title": namespace_title},
            headers=self._get_auth_headers(),
        )

        # A concurrent run may have created it after our lookup.
        if response.status_code >= 400:
            existing_namespace_id = self._find_namespace_id_by_title(namespace_title)
            if existing_namespace_id:
                self._tables[benchmark][name] = existing_namespace_id
                return existing_namespace_id
            response.raise_for_status()

        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(
                f"Failed to create KV namespace {namespace_title}: {payload.get('errors')}"
            )

        namespace_id = payload.get("result", {}).get("id")
        if not namespace_id:
            raise RuntimeError(
                f"Cloudflare KV API did not return namespace id for {namespace_title}"
            )

        self._tables[benchmark][name] = namespace_id
        self.logging.info(
            f"Created KV namespace '{namespace_title}' ({namespace_id}) for benchmark {benchmark}"
        )
        return namespace_id

    def write_to_table(
        self,
        benchmark: str,
        table: str,
        data: dict,
        primary_key: Tuple[str, str],
        secondary_key: Optional[Tuple[str, str]] = None,
    ):
        namespace_id = self._get_table_name(benchmark, table)
        if not namespace_id:
            raise ValueError(f"Table {table} not found for benchmark {benchmark}")

        record = dict(data)
        for key in (primary_key, secondary_key):
            if key is not None:
                record[key[0]] = key[1]

        composite_key = self._compose_key(primary_key, secondary_key)
        value = json.dumps(record, separators=(",", ":"), default=str)

        response = requests.put(
            f"{self._kv_api_base()}/{namespace_id}/values/{quote(composite_key, safe='')}",
            data=value.encode("utf-8"),
            headers=self._get_auth_headers(content_type="text/plain;charset=UTF-8"),
        )
        response.raise_for_status()

        if secondary_key is not None:
            primary_value = str(primary_key[1])
            secondary_value = str(secondary_key[1])
            index_values = self._read_index(namespace_id, primary_value)
            if secondary_value not in index_values:
                index_values.append(secondary_value)
                self._write_index(namespace_id, primary_value, index_values)

    def clear_table(self, name: str) -> str:
        self.logging.warning(
            "Cloudflare KV clear_table is not implemented. Use remove_table() + create_table() instead."
        )
        return name

    def remove_table(self, name: str) -> str:
        benchmark_to_modify: Optional[str] = None
        logical_name_to_delete: Optional[str] = None
        namespace_id_to_delete: Optional[str] = None

        for benchmark, tables in list(self._tables.items()):
            for logical_name, namespace_id in list(tables.items()):
                if name == logical_name or name == namespace_id:
                    benchmark_to_modify = benchmark
                    logical_name_to_delete = logical_name
                    namespace_id_to_delete = namespace_id
                    break
            if namespace_id_to_delete:
                break

        # Also allow direct removal by namespace id when not present in local mapping.
        if namespace_id_to_delete is None and self._is_namespace_id(name):
            namespace_id_to_delete = name

        if namespace_id_to_delete is None:
            self.logging.warning(f"KV table '{name}' not found in local mapping.")
            return name

        self._delete_namespace(namespace_id_to_delete)

        if benchmark_to_modify is not None and logical_name_to_delete is not None:
            del self._tables[benchmark_to_modify][logical_name_to_delete]

        self.logging.info(f"Removed KV namespace {namespace_id_to_delete}")
        return name

    def envs(self) -> dict:
        return {"NOSQL_STORAGE_DATABASE": "kvstore"}

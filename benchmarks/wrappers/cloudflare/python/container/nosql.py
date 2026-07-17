"""
NoSQL module for Cloudflare Python Containers.

Issues HTTP POSTs to the sebs.kv virtual host, handled by the Worker outbound binding handler. The server side is
implemented in benchmarks/wrappers/cloudflare/nodejs/container/worker.js
(handleNoSQLRequest), which is copied into every container project at deploy
time by sebs/cloudflare/containers.py because @cloudflare/containers is
Node.js-only and wraps Python containers as well.
"""
import json
import urllib.request
import urllib.parse
from typing import List, Optional, Tuple


class nosql:
    """NoSQL client for containers using the Worker's outbound KV handler."""
    
    instance: Optional["nosql"] = None
    worker_url = None  # Legacy public proxy URL, retained for compatibility
    outbound_url = "http://sebs.kv"

    @staticmethod
    def init_instance(*args, **kwargs):
        """Initialize singleton instance"""
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance
    
    @staticmethod
    def set_worker_url(url):
        """Retain the legacy public proxy URL for older handlers."""
        nosql.worker_url = url

    def _make_request(self, operation: str, params: dict) -> dict:
        """Make an HTTP request to the Worker outbound KV handler."""
        if not nosql.outbound_url:
            raise RuntimeError("Outbound handler URL is not configured - cannot access NoSQL")
        
        url = f"{nosql.outbound_url}/nosql/{operation}"
        data = json.dumps(params).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(error_body)
                raise RuntimeError(f"NoSQL operation failed: {error_data.get('error', error_body)}")
            except json.JSONDecodeError:
                raise RuntimeError(f"NoSQL operation failed: {error_body}")
        except Exception as e:
            raise RuntimeError(f"NoSQL operation failed: {e}")

    def insert(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        params = {
            'table_name': table_name,
            'primary_key': list(primary_key),
            'secondary_key': list(secondary_key),
            'data': data
        }
        return self._make_request('insert', params)

    def update(
        self,
        table_name: str,
        primary_key: Tuple[str, str],
        secondary_key: Tuple[str, str],
        data: dict,
    ):
        params = {
            'table_name': table_name,
            'primary_key': list(primary_key),
            'secondary_key': list(secondary_key),
            'data': data
        }
        return self._make_request('update', params)

    def get(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]
    ) -> Optional[dict]:
        params = {
            'table_name': table_name,
            'primary_key': list(primary_key),
            'secondary_key': list(secondary_key)
        }
        result = self._make_request('get', params)
        return result.get('data')

    def query(
        self, table_name: str, primary_key: Tuple[str, str], secondary_key_name: str
    ) -> List[dict]:
        params = {
            'table_name': table_name,
            'primary_key': list(primary_key),
            'secondary_key_name': secondary_key_name
        }
        result = self._make_request('query', params)
        return result.get('items', [])

    def delete(self, table_name: str, primary_key: Tuple[str, str], secondary_key: Tuple[str, str]):
        params = {
            'table_name': table_name,
            'primary_key': list(primary_key),
            'secondary_key': list(secondary_key)
        }
        return self._make_request('delete', params)

    @staticmethod
    def get_instance():
        if nosql.instance is None:
            nosql.instance = nosql()
        return nosql.instance

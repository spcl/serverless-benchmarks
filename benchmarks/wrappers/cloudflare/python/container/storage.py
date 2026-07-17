"""
Storage module for Cloudflare Python Containers
Uses a Container outbound handler to access the Worker R2 binding's R2 binding
"""
import io
import os
import json
import urllib.request
import urllib.parse


class storage:
    """R2 storage client for containers using a Worker outbound binding handler"""
    instance = None
    outbound_url = "http://sebs.r2"
    
    def __init__(self):
        # R2 calls use the Worker outbound handler virtual host.
        self.r2_enabled = True
    
    @staticmethod
    def init_instance(entry=None):
        """Initialize singleton instance"""
        if storage.instance is None:
            storage.instance = storage()
        return storage.instance
    
    @staticmethod
    def get_instance():
        """Get singleton instance"""
        if storage.instance is None:
            storage.init_instance()
        return storage.instance
    
    @staticmethod
    def unique_name(name):
        """Generate unique name for file"""
        import uuid
        name_part, extension = os.path.splitext(name)
        return f'{name_part}.{str(uuid.uuid4()).split("-")[0]}{extension}'
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post_json(self, url: str, body: bytes = b'', content_type: str = 'application/octet-stream'):
        """POST *body* to *url* and return the parsed JSON response."""
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', content_type)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8'))


    def _upload_bytes(self, key: str, data: bytes) -> str:
        return self._single_upload(key, data)

    def _single_upload(self, key: str, data: bytes) -> str:
        params = urllib.parse.urlencode({'key': key})
        url = f"{storage.outbound_url}/r2/upload?{params}"
        result = self._post_json(url, data)
        return result['key']


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload_stream(self, bucket: str, key: str, data):
        """Upload data to R2 via the outbound handler"""
        if not self.r2_enabled:
            print("Warning: R2 not configured, skipping upload")
            return key
        
        if not storage.outbound_url:
            raise RuntimeError("Outbound handler URL is not configured - cannot access R2")
        
        # Handle BytesIO objects
        if isinstance(data, io.BytesIO):
            data = data.getvalue()
        
        # Convert to bytes if needed
        if isinstance(data, str):
            data = data.encode('utf-8')

        unique_key = self.unique_name(key)
        
        try:
            return self._upload_bytes(unique_key, data)
        except Exception as e:
            print(f"R2 upload error: {e}")
            raise RuntimeError(f"Failed to upload to R2: {e}")

    def download_stream(self, bucket: str, key: str) -> bytes:
        """Download data from R2 via the outbound handler"""
        if not self.r2_enabled:
            raise RuntimeError("R2 not configured")
        
        if not storage.outbound_url:
            raise RuntimeError("Outbound handler URL is not configured - cannot access R2")
        
        # Download through the Worker outbound handler.
        params = urllib.parse.urlencode({'bucket': bucket, 'key': key})
        url = f"{storage.outbound_url}/r2/download?{params}"
        
        try:
            with urllib.request.urlopen(url) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"Object not found: {key}")
            else:
                raise RuntimeError(f"Failed to download from R2: {e}")
        except Exception as e:
            print(f"R2 download error: {e}")
            raise RuntimeError(f"Failed to download from R2: {e}")
    
    def upload(self, bucket, key, filepath, unique_name=True):
        """Upload file from disk."""
        upload_key = self.unique_name(key) if unique_name else key
        with open(filepath, 'rb') as f:
            data = f.read()
        try:
            self._upload_bytes(upload_key, data)
        except Exception as e:
            raise RuntimeError(f"Failed to upload to R2: {e}")
        return upload_key
    
    def _upload_with_key(self, bucket: str, key: str, data):
        """Upload data to R2 via the outbound handler with exact key (internal method)"""
        if not self.r2_enabled:
            print("Warning: R2 not configured, skipping upload")
            return
        
        if not storage.outbound_url:
            raise RuntimeError("Outbound handler URL is not configured - cannot access R2")
        
        # Handle BytesIO objects
        if isinstance(data, io.BytesIO):
            data = data.getvalue()
        
        # Convert to bytes if needed
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        try:
            result_key = self._upload_bytes(key, data)
            print(f"[storage._upload_with_key] Upload successful, key={result_key}")
        except Exception as e:
            print(f"R2 upload error: {e}")
            raise RuntimeError(f"Failed to upload to R2: {e}")
    
    def download(self, bucket, key, filepath):
        """Download file to disk"""
        data = self.download_stream(bucket, key)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(data)

    def download_within_range(self, bucket: str, key: str, start_bytes: int, end_bytes: int) -> str:
        """Download a byte range of an object from R2 via the worker proxy."""
        if not self.r2_enabled:
            raise RuntimeError("R2 not configured")

        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")

        params = urllib.parse.urlencode({'bucket': bucket, 'key': key})
        url = f"{storage.worker_url}/r2/download?{params}"

        req = urllib.request.Request(url)
        req.add_header('Range', f'bytes={start_bytes}-{end_bytes}')

        try:
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            if e.code in (206, 200):
                return e.read().decode('utf-8')
            raise RuntimeError(f"Failed to download range from R2: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to download range from R2: {e}")

    def list_directory(self, bucket, prefix):
        """List all object keys with a given prefix."""
        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")
        params = urllib.parse.urlencode({'bucket': bucket, 'prefix': prefix})
        list_url = f"{storage.worker_url}/r2/list?{params}"
        with urllib.request.urlopen(list_url) as response:
            result = json.loads(response.read().decode('utf-8'))
            return [obj['key'] for obj in result.get('objects', [])]

    def download_directory(self, bucket, prefix, local_path):
        """
        Download all files with a given prefix to a local directory.
        Lists objects via /r2/list endpoint and downloads each one in parallel.
        """
        import concurrent.futures

        if not storage.outbound_url:
            raise RuntimeError("Outbound handler URL is not configured - cannot access R2")
        
        # Create local directory
        os.makedirs(local_path, exist_ok=True)
        
        # List objects with prefix through the Worker outbound handler.
        params = urllib.parse.urlencode({'bucket': bucket, 'prefix': prefix})
        list_url = f"{storage.outbound_url}/r2/list?{params}"
        
        try:
            with urllib.request.urlopen(list_url) as response:
                result = json.loads(response.read().decode('utf-8'))
                objects = result.get('objects', [])
                
                print(f"Found {len(objects)} objects with prefix '{prefix}'")

                def _download_one(obj):
                    obj_key = obj['key']
                    local_file_path = os.path.join(local_path, obj_key)
                    local_dir = os.path.dirname(local_file_path)
                    if local_dir:
                        os.makedirs(local_dir, exist_ok=True)
                    print(f"Downloading {obj_key} to {local_file_path}")
                    self.download(bucket, obj_key, local_file_path)

                # Download all objects in parallel (up to 16 concurrent)
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
                    futures = [executor.submit(_download_one, obj) for obj in objects]
                    for fut in concurrent.futures.as_completed(futures):
                        fut.result()  # re-raise any exception

                return local_path
                
        except Exception as e:
            print(f"Error listing/downloading directory: {e}")
            raise RuntimeError(f"Failed to download directory: {e}")

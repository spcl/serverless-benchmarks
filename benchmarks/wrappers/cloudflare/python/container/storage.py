"""
Storage module for Cloudflare Python Containers
Uses HTTP proxy to access R2 storage through the Worker's R2 binding
"""
import io
import mimetypes
import os
import json
import urllib.request
import urllib.parse

def _guess_content_type(name: str) -> str:
    """Infer MIME type from a file name, falling back to application/octet-stream."""
    ct, _ = mimetypes.guess_type(name)
    return ct or 'application/octet-stream'

# Cloudflare Workers enforce a 100 MB request body limit at the edge.
# Use multipart upload for payloads larger than this threshold so that
# each individual request stays well below that limit.
_MULTIPART_THRESHOLD = 10 * 1024 * 1024   # 10 MB
_PART_SIZE          = 10 * 1024 * 1024   # 10 MB per part (R2 min is 5 MB)

class storage:
    """R2 storage client for containers using HTTP proxy to Worker"""
    instance = None
    worker_url = None  # Set by handler from X-Worker-URL header
    
    def __init__(self):
        # Container accesses R2 through worker.js proxy
        # Worker URL is injected via X-Worker-URL header in each request
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
    def set_worker_url(url):
        """Set worker URL for R2 proxy (called by handler)"""
        storage.worker_url = url
    
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

    def _upload_bytes(self, key: str, data: bytes, content_type: str = 'application/octet-stream') -> str:
        """Upload *data* to the exact R2 *key* via the worker proxy.

        Uses a single PUT for small payloads and R2 multipart upload for
        payloads that exceed _MULTIPART_THRESHOLD (to stay under Cloudflare's
        100 MB per-request edge limit).

        Returns the R2 key.
        """
        if len(data) <= _MULTIPART_THRESHOLD:
            return self._single_upload(key, data, content_type)
        return self._multipart_upload(key, data, content_type)

    def _single_upload(self, key: str, data: bytes, content_type: str = 'application/octet-stream') -> str:
        params = urllib.parse.urlencode({'key': key})
        url = f"{storage.worker_url}/r2/upload?{params}"
        result = self._post_json(url, data, content_type)
        return result['key']

    def _multipart_upload(self, key: str, data: bytes, content_type: str = 'application/octet-stream') -> str:
        """Split *data* into ≤_PART_SIZE chunks and use R2 multipart upload."""
        # 1. Initiate
        params = urllib.parse.urlencode({'key': key, 'contentType': content_type})
        init_url = f"{storage.worker_url}/r2/multipart-init?{params}"
        init = self._post_json(init_url)
        upload_id = init['uploadId']
        upload_key = init['key']
        print(f"[storage] multipart upload initiated: key={upload_key}, uploadId={upload_id}, "
              f"total={len(data):,} bytes, parts={-(-len(data)//_PART_SIZE)}")

        # 2. Upload parts
        completed_parts = []
        for part_num, offset in enumerate(range(0, len(data), _PART_SIZE), start=1):
            chunk = data[offset:offset + _PART_SIZE]
            params = urllib.parse.urlencode({
                'key': upload_key,
                'uploadId': upload_id,
                'partNumber': part_num,
            })
            part_url = f"{storage.worker_url}/r2/multipart-part?{params}"
            part = self._post_json(part_url, chunk)
            completed_parts.append({'partNumber': part['partNumber'], 'etag': part['etag']})
            print(f"[storage] uploaded part {part_num}, etag={part['etag']}")

        # 3. Complete
        params = urllib.parse.urlencode({'key': upload_key, 'uploadId': upload_id})
        complete_url = f"{storage.worker_url}/r2/multipart-complete?{params}"
        result = self._post_json(
            complete_url,
            json.dumps({'parts': completed_parts}).encode('utf-8'),
            content_type='application/json',
        )
        print(f"[storage] multipart upload complete: key={result['key']}")
        return result['key']

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload_stream(self, bucket: str, key: str, data):
        """Upload data to R2 via worker proxy"""
        if not self.r2_enabled:
            print("Warning: R2 not configured, skipping upload")
            return key
        
        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")
        
        # Handle BytesIO objects
        if isinstance(data, io.BytesIO):
            data = data.getvalue()
        
        # Convert to bytes if needed
        if isinstance(data, str):
            data = data.encode('utf-8')

        unique_key = self.unique_name(key)
        
        try:
            return self._upload_bytes(unique_key, data, _guess_content_type(unique_key))
        except Exception as e:
            print(f"R2 upload error: {e}")
            raise RuntimeError(f"Failed to upload to R2: {e}")
    
    def download_stream(self, bucket: str, key: str) -> bytes:
        """Download data from R2 via worker proxy"""
        if not self.r2_enabled:
            raise RuntimeError("R2 not configured")
        
        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")
        
        # Download via worker proxy
        params = urllib.parse.urlencode({'bucket': bucket, 'key': key})
        url = f"{storage.worker_url}/r2/download?{params}"
        
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
    
    def upload(self, bucket, key, filepath):
        """Upload file from disk with unique key generation"""
        # Generate unique key to avoid conflicts
        unique_key = self.unique_name(key)
        content_type = _guess_content_type(filepath)
        with open(filepath, 'rb') as f:
            data = f.read()
        try:
            self._upload_bytes(unique_key, data, content_type)
        except Exception as e:
            raise RuntimeError(f"Failed to upload to R2: {e}")
        return unique_key
    
    def _upload_with_key(self, bucket: str, key: str, data):
        """Upload data to R2 via worker proxy with exact key (internal method)"""
        if not self.r2_enabled:
            print("Warning: R2 not configured, skipping upload")
            return
        
        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")
        
        # Handle BytesIO objects
        if isinstance(data, io.BytesIO):
            data = data.getvalue()
        
        # Convert to bytes if needed
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        try:
            result_key = self._upload_bytes(key, data, _guess_content_type(key))
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
    
    def download_directory(self, bucket, prefix, local_path):
        """
        Download all files with a given prefix to a local directory.
        Lists objects via /r2/list endpoint and downloads each one in parallel.
        """
        import concurrent.futures

        if not storage.worker_url:
            raise RuntimeError("Worker URL not set - cannot access R2")
        
        # Create local directory
        os.makedirs(local_path, exist_ok=True)
        
        # List objects with prefix via worker proxy
        params = urllib.parse.urlencode({'bucket': bucket, 'prefix': prefix})
        list_url = f"{storage.worker_url}/r2/list?{params}"
        
        try:
            req = urllib.request.Request(list_url)
            req.add_header('User-Agent', 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2')
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                objects = result.get('objects', [])
                
                print(f"Found {len(objects)} objects with prefix '{prefix}'")

                def _download_one(obj):
                    obj_key = obj['key']
                    relative_path = obj_key
                    if prefix and obj_key.startswith(prefix):
                        relative_path = obj_key[len(prefix):].lstrip('/')
                    local_file_path = os.path.join(local_path, relative_path)
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

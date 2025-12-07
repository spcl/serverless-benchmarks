"""
Storage module for Cloudflare Python Containers
Uses HTTP proxy to access R2 storage through the Worker's R2 binding
"""
import io
import os
import json
import urllib.request
import urllib.parse

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
        
        # Upload via worker proxy
        params = urllib.parse.urlencode({'bucket': bucket, 'key': key})
        url = f"{storage.worker_url}/r2/upload?{params}"
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/octet-stream')
        
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['key']
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
        print(f"!!! [storage.upload] bucket={bucket}, key={key}, unique_key={unique_key}, filepath={filepath}")
        
        with open(filepath, 'rb') as f:
            data = f.read()
            print(f"!!! [storage.upload] Read {len(data)} bytes from {filepath}")
            # Upload with the unique key
            self._upload_with_key(bucket, unique_key, data)
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
        
        # Upload via worker proxy with exact key
        params = urllib.parse.urlencode({'bucket': bucket, 'key': key})
        url = f"{storage.worker_url}/r2/upload?{params}"
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/octet-stream')
        
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                print(f"!!! [storage._upload_with_key] Upload successful, key={result['key']}")
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
        Lists objects via /r2/list endpoint and downloads each one.
        """
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
                
                # Download each object
                for obj in objects:
                    obj_key = obj['key']
                    # Create local file path by removing the prefix
                    relative_path = obj_key
                    if prefix and obj_key.startswith(prefix):
                        relative_path = obj_key[len(prefix):].lstrip('/')
                    
                    local_file_path = os.path.join(local_path, relative_path)
                    
                    # Create directory structure if needed
                    local_dir = os.path.dirname(local_file_path)
                    if local_dir:
                        os.makedirs(local_dir, exist_ok=True)
                    
                    # Download the file
                    print(f"Downloading {obj_key} to {local_file_path}")
                    self.download(bucket, obj_key, local_file_path)
                
                return local_path
                
        except Exception as e:
            print(f"Error listing/downloading directory: {e}")
            raise RuntimeError(f"Failed to download directory: {e}")

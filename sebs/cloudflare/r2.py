import json
import os

import requests
from sebs.cloudflare.config import CloudflareCredentials
from sebs.faas.storage import PersistentStorage
from sebs.faas.config import Resources
from sebs.cache import Cache

from typing import List, Optional
class R2(PersistentStorage):
    @staticmethod
    def typename() -> str:
        return "Cloudlfare.R2"

    @staticmethod
    def deployment_name() -> str:
        return "cloudflare"

    @property
    def replace_existing(self) -> bool:
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        self._replace_existing = val

    def __init__(
        self,
        region: str,
        cache_client: Cache,
        resources: Resources,
        replace_existing: bool,
        credentials: CloudflareCredentials,
    ):
        super().__init__(region, cache_client, resources, replace_existing)
        self._credentials = credentials

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

    def correct_name(self, name: str) -> str:
        return name

    def _create_bucket(
        self, name: str, buckets: list[str] = [], randomize_name: bool = False
    ) -> str:
        for bucket_name in buckets:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(
                        bucket_name, name
                    )
                )
                return bucket_name

        account_id = self._credentials.account_id

        create_bucket_uri = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets"
        )

        # R2 API only accepts "name" parameter - locationHint is optional and must be one of:
        # "apac", "eeur", "enam", "weur", "wnam"
        # WARNING: locationHint is not currently supported by SeBS. Buckets are created
        # with Cloudflare's automatic location selection.
        params = {"name": name}
        
        self.logging.warning(
            f"Creating R2 bucket '{name}' without locationHint. "
            "Geographic location is determined automatically by Cloudflare."
        )

        try:
            create_bucket_response = requests.post(
                create_bucket_uri, json=params, headers=self._get_auth_headers()
            )
            
            # Log the response for debugging
            if create_bucket_response.status_code >= 400:
                try:
                    error_data = create_bucket_response.json()
                    self.logging.error(
                        f"R2 bucket creation failed. Status: {create_bucket_response.status_code}, "
                        f"Response: {error_data}"
                    )
                except:
                    self.logging.error(
                        f"R2 bucket creation failed. Status: {create_bucket_response.status_code}, "
                        f"Response: {create_bucket_response.text}"
                    )
            
            create_bucket_response.raise_for_status()
            
            bucket_info_json = create_bucket_response.json()

            if not bucket_info_json.get("success"):
                self.logging.error(f"Failed to create R2 bucket: {bucket_info_json.get('errors')}")
                raise RuntimeError(f"Failed to create R2 bucket {name}")

            bucket_name = bucket_info_json.get("result", {}).get("name", name)
            self.logging.info(f"Created R2 bucket {bucket_name}")
            return bucket_name
            
        except requests.exceptions.RequestException as e:
            self.logging.error(f"Error creating R2 bucket {name}: {e}")
            raise

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        """
        Download a file from a bucket.

        :param bucket_name:
        :param key: storage source filepath
        :param filepath: local destination filepath
        """
        # R2 requires S3-compatible access for object operations
        # For now, this is not fully implemented
        self.logging.warning(f"download not fully implemented for R2 bucket {bucket_name}")
        pass

    def upload(self, bucket_name: str, filepath: str, key: str):
        """
        Upload a file to R2 bucket using the S3-compatible API.
        
        Requires S3 credentials to be configured for the R2 bucket.

        :param bucket_name: R2 bucket name
        :param filepath: local source filepath
        :param key: R2 destination key/path
        """
        try:
            import boto3
            from botocore.config import Config
            
            account_id = self._credentials.account_id
            
            # R2 uses S3-compatible API, but requires special configuration
            # The endpoint is: https://<account_id>.r2.cloudflarestorage.com
            # You need to create R2 API tokens in the Cloudflare dashboard
            
            # Check if we have S3-compatible credentials
            if not self._credentials.r2_access_key_id or not self._credentials.r2_secret_access_key:
                self.logging.warning(
                    "R2 upload requires S3-compatible API credentials (r2_access_key_id, r2_secret_access_key). "
                    "File upload skipped. Set CLOUDFLARE_R2_ACCESS_KEY_ID and CLOUDFLARE_R2_SECRET_ACCESS_KEY."
                )
                return
            
            s3_client = boto3.client(
                's3',
                endpoint_url=f'https://{account_id}.r2.cloudflarestorage.com',
                aws_access_key_id=self._credentials.r2_access_key_id,
                aws_secret_access_key=self._credentials.r2_secret_access_key,
                config=Config(signature_version='s3v4'),
                region_name='auto'
            )
            
            with open(filepath, 'rb') as f:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=f
                )
            
            self.logging.debug(f"Uploaded {filepath} to R2 bucket {bucket_name} as {key}")
            
        except ImportError:
            self.logging.warning(
                "boto3 not available. Install with: pip install boto3. "
                "File upload to R2 skipped."
            )
        except Exception as e:
            self.logging.warning(f"Failed to upload {filepath} to R2: {e}")
    
    def upload_bytes(self, bucket_name: str, key: str, data: bytes):
        """
        Upload bytes directly to R2 bucket using the S3-compatible API.
        
        :param bucket_name: R2 bucket name
        :param key: R2 destination key/path
        :param data: bytes to upload
        """
        try:
            import boto3
            from botocore.config import Config
            
            account_id = self._credentials.account_id
            
            if not self._credentials.r2_access_key_id or not self._credentials.r2_secret_access_key:
                self.logging.warning(
                    "R2 upload requires S3-compatible API credentials (r2_access_key_id, r2_secret_access_key). "
                    "Upload skipped. Set CLOUDFLARE_R2_ACCESS_KEY_ID and CLOUDFLARE_R2_SECRET_ACCESS_KEY environment variables."
                )
                return
            
            s3_client = boto3.client(
                's3',
                endpoint_url=f'https://{account_id}.r2.cloudflarestorage.com',
                aws_access_key_id=self._credentials.r2_access_key_id,
                aws_secret_access_key=self._credentials.r2_secret_access_key,
                config=Config(signature_version='s3v4'),
                region_name='auto'
            )
            
            s3_client.put_object(
                Bucket=bucket_name,
                Key=key,
                Body=data
            )
            
            self.logging.debug(f"Uploaded {len(data)} bytes to R2 bucket {bucket_name} as {key}")
            
        except ImportError:
            self.logging.warning(
                "boto3 not available. Install with: pip install boto3"
            )
        except Exception as e:
            self.logging.warning(f"Failed to upload bytes to R2: {e}")

    """
        Retrieves list of files in a bucket.

        :param bucket_name:
        :return: list of files in a given bucket
    """

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        Retrieves list of files in a bucket using S3-compatible API.
        
        :param bucket_name:
        :param prefix: optional prefix filter
        :return: list of files in a given bucket
        """
        # Use S3-compatible API with R2 credentials
        if not self._credentials.r2_access_key_id or not self._credentials.r2_secret_access_key:
            self.logging.warning(f"R2 S3 credentials not configured, cannot list bucket {bucket_name}")
            return []
        
        try:
            import boto3
            from botocore.config import Config
            
            account_id = self._credentials.account_id
            r2_endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
            
            s3_client = boto3.client(
                's3',
                endpoint_url=r2_endpoint,
                aws_access_key_id=self._credentials.r2_access_key_id,
                aws_secret_access_key=self._credentials.r2_secret_access_key,
                config=Config(signature_version='s3v4'),
                region_name='auto'
            )
            
            # List objects with optional prefix
            paginator = s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
            
            files = []
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        files.append(obj['Key'])
            
            return files
            
        except Exception as e:
            self.logging.warning(f"Failed to list R2 bucket {bucket_name}: {str(e)}")
            return []

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List all R2 buckets in the account.
        
        :param bucket_name: optional filter (not used for R2)
        :return: list of bucket names
        """
        account_id = self._credentials.account_id
        
        list_buckets_uri = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets"
        )
        
        try:
            response = requests.get(list_buckets_uri, headers=self._get_auth_headers())
            
            # Log detailed error information
            if response.status_code == 403:
                try:
                    error_data = response.json()
                    self.logging.error(
                        f"403 Forbidden accessing R2 buckets. "
                        f"Response: {error_data}. "
                        f"Your API token may need 'R2 Read and Write' permissions."
                    )
                except:
                    self.logging.error(
                        f"403 Forbidden accessing R2 buckets. "
                        f"Your API token may need 'R2 Read and Write' permissions."
                    )
                return []
            
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("success"):
                self.logging.error(f"Failed to list R2 buckets: {data.get('errors')}")
                return []
            
            # Extract bucket names from response
            buckets = data.get("result", {}).get("buckets", [])
            bucket_names = [bucket["name"] for bucket in buckets]
            
            self.logging.info(f"Found {len(bucket_names)} R2 buckets")
            return bucket_names
            
        except requests.exceptions.RequestException as e:
            self.logging.error(f"Error listing R2 buckets: {e}")
            return []

    def exists_bucket(self, bucket_name: str) -> bool:
        """
        Check if a bucket exists.
        
        :param bucket_name:
        :return: True if bucket exists
        """
        buckets = self.list_buckets()
        return bucket_name in buckets

    def clean_bucket(self, bucket_name: str):
        """
        Remove all objects from a bucket.
        
        :param bucket_name:
        """
        self.logging.warning(f"clean_bucket not fully implemented for R2 bucket {bucket_name}")
        pass

    def remove_bucket(self, bucket: str):
        """
        Delete a bucket.
        
        :param bucket:
        """
        account_id = self._credentials.account_id
        
        delete_bucket_uri = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket}"
        )
        
        try:
            response = requests.delete(delete_bucket_uri, headers=self._get_auth_headers())
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("success"):
                self.logging.info(f"Successfully deleted R2 bucket {bucket}")
            else:
                self.logging.error(f"Failed to delete R2 bucket {bucket}: {data.get('errors')}")
                
        except requests.exceptions.RequestException as e:
            self.logging.error(f"Error deleting R2 bucket {bucket}: {e}")

    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        """
        Upload a file to a bucket (used for parallel uploads).
        
        :param bucket_idx: index of the bucket/prefix to upload to
        :param file: destination file name/key
        :param filepath: source file path
        """
        # Skip upload when using cached buckets and not updating storage
        if self.cached and not self.replace_existing:
            return

        # Build the key with the input prefix
        key = os.path.join(self.input_prefixes[bucket_idx], file)

        bucket_name = self.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        
        # Check if file already exists (if not replacing existing files)
        if not self.replace_existing:
            for f in self.input_prefixes_files[bucket_idx]:
                if key == f:
                    self.logging.info(f"Skipping upload of {filepath} to {bucket_name} (already exists)")
                    return

        # Upload the file
        self.upload(bucket_name, filepath, key)

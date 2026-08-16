"""Cloudflare R2 object storage implementation."""

import os

import requests
from sebs.cloudflare.config import CloudflareCredentials
from sebs.faas.storage import PersistentStorage
from sebs.faas.config import Resources
from sebs.cache import Cache

from typing import List, Optional


class R2(PersistentStorage):
    """Cloudflare R2 object storage backend for SeBS benchmarks."""

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this storage class."""
        return "Cloudflare.R2"

    @staticmethod
    def deployment_name() -> str:
        """Return the deployment platform name."""
        return "cloudflare"

    @property
    def replace_existing(self) -> bool:
        """Whether existing objects should be overwritten on upload."""
        return self._replace_existing

    @replace_existing.setter
    def replace_existing(self, val: bool):
        """Set whether existing objects should be overwritten on upload."""
        self._replace_existing = val

    def __init__(
        self,
        region: str,
        cache_client: Cache,
        resources: Resources,
        replace_existing: bool,
        credentials: CloudflareCredentials,
    ):
        """Initialize R2 storage with Cloudflare credentials."""
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

    def _get_api_base_url(self) -> str:
        """Get the base URL for R2 API operations."""
        id = self._credentials.account_id
        return f"https://api.cloudflare.com/client/v4/accounts/{id}/r2/buckets"

    def correct_name(self, name: str) -> str:
        """Return the bucket name unchanged; R2 does not require name transformations."""
        return name

    def _create_bucket(
        self, name: str, buckets: Optional[List[str]] = None, randomize_name: bool = False
    ) -> str:
        """Create an R2 bucket, reusing an existing one if the name is already present."""
        for bucket_name in buckets or []:
            if name in bucket_name:
                self.logging.info(
                    "Bucket {} for {} already exists, skipping.".format(bucket_name, name)
                )
                return bucket_name

        account_id = self._credentials.account_id

        create_bucket_uri = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets"

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
                except Exception:
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
        Download a file from a bucket using the Cloudflare REST API.

        :param bucket_name:
        :param key: storage source filepath
        :param filepath: local destination filepath
        :raises RuntimeError: if download fails
        """
        # URL-encode the key for the API path
        from urllib.parse import quote

        encoded_key = quote(key, safe="")
        url = f"{self._get_api_base_url()}/{bucket_name}/objects/{encoded_key}"

        try:
            dirname = os.path.dirname(filepath)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            response = requests.get(url, headers=self._get_auth_headers(), stream=True)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            self.logging.debug(f"Downloaded {key} from R2 bucket {bucket_name} to {filepath}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to download {key} from R2: {e}") from e

    def upload(self, bucket_name: str, filepath: str, key: str):
        """
        Upload a file to R2 bucket using the Cloudflare REST API.

        Note: REST API has a 300MB file size limit. Benchmark data files
        exceeding this limit should be split or uploaded via Workers bindings.

        :param bucket_name: R2 bucket name
        :param filepath: local source filepath
        :param key: R2 destination key/path
        :raises RuntimeError: if upload fails
        """
        from urllib.parse import quote

        encoded_key = quote(key, safe="")
        url = f"{self._get_api_base_url()}/{bucket_name}/objects/{encoded_key}"

        try:
            file_size = os.path.getsize(filepath)
            if file_size > 300 * 1024 * 1024:  # 300MB limit
                raise RuntimeError(
                    f"File {filepath} is {file_size / 1024 / 1024:.1f}MB, "
                    "which exceeds the 300MB REST API limit."
                )

            with open(filepath, "rb") as f:
                # Use content-type based on file extension
                import mimetypes

                content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
                headers = self._get_auth_headers()
                headers["Content-Type"] = content_type

                response = requests.put(url, headers=headers, data=f)
                response.raise_for_status()

            self.logging.debug(f"Uploaded {filepath} to R2 bucket {bucket_name} as {key}")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to upload {filepath} to R2: {e}") from e

    def upload_bytes(self, bucket_name: str, key: str, data: bytes):
        """
        Upload bytes directly to R2 bucket using the Cloudflare REST API.

        :param bucket_name: R2 bucket name
        :param key: R2 destination key/path
        :param data: bytes to upload
        :raises RuntimeError: if upload fails
        """
        from urllib.parse import quote

        encoded_key = quote(key, safe="")
        url = f"{self._get_api_base_url()}/{bucket_name}/objects/{encoded_key}"

        try:
            if len(data) > 300 * 1024 * 1024:  # 300MB limit
                raise RuntimeError(
                    f"Data is {len(data) / 1024 / 1024:.1f}MB, "
                    "which exceeds the 300MB REST API limit."
                )

            headers = self._get_auth_headers()
            headers["Content-Type"] = "application/octet-stream"

            response = requests.put(url, headers=headers, data=data)
            response.raise_for_status()

            self.logging.debug(f"Uploaded {len(data)} bytes to R2 bucket {bucket_name} as {key}")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to upload bytes to R2: {e}") from e

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        """
        Retrieves list of files in a bucket using the Cloudflare REST API.

        :param bucket_name:
        :param prefix: optional prefix filter
        :return: list of files in a given bucket
        """
        url = f"{self._get_api_base_url()}/{bucket_name}/objects"
        files = []
        cursor = None

        try:
            while True:
                params = {}
                if prefix:
                    params["prefix"] = prefix
                if cursor:
                    params["cursor"] = cursor

                response = requests.get(url, headers=self._get_auth_headers(), params=params)
                response.raise_for_status()

                data = response.json()
                if not data.get("success"):
                    raise RuntimeError(f"Failed to list R2 bucket: {data.get('errors')}")

                # The result is a list of objects directly
                objects = data.get("result", [])
                if objects is None:
                    objects = []

                for obj in objects:
                    files.append(obj["key"])

                # Check for pagination via result_info
                result_info = data.get("result_info", {})
                cursor = result_info.get("cursor")
                if not cursor:
                    break

            return files

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to list R2 bucket {bucket_name}: {str(e)}") from e

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        """
        List all R2 buckets in the account.

        :param bucket_name: optional filter (not used for R2)
        :return: list of bucket names
        """
        account_id = self._credentials.account_id

        list_buckets_uri = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets"

        try:
            response = requests.get(list_buckets_uri, headers=self._get_auth_headers())

            if response.status_code == 403:
                try:
                    error_data = response.json()
                    detail = f"Response: {error_data}. "
                except ValueError:
                    detail = ""
                raise RuntimeError(
                    f"403 Forbidden accessing R2 buckets. {detail}"
                    "Your API token may need 'R2 Read and Write' permissions."
                )

            response.raise_for_status()

            data = response.json()

            if not data.get("success"):
                raise RuntimeError(f"Failed to list R2 buckets: {data.get('errors')}")

            buckets = data.get("result", {}).get("buckets", [])
            bucket_names = [bucket["name"] for bucket in buckets]

            self.logging.info(f"Found {len(bucket_names)} R2 buckets")
            return bucket_names

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error listing R2 buckets: {e}") from e

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
        :raises RuntimeError: if bucket deletion fails
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
                raise RuntimeError(f"Failed to delete R2 bucket {bucket}: {data.get('errors')}")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error deleting R2 bucket {bucket}: {e}") from e

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
                    self.logging.info(
                        f"Skipping upload of {filepath} to {bucket_name} (already exists)"
                    )
                    return

        # Upload the file
        self.upload(bucket_name, filepath, key)

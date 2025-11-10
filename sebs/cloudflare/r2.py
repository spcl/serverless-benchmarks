import json

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

        get_bucket_uri = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets"
        )

        params = {"name": "cloudflare_bucket", "locationHint": self._region}

        create_bucket_response = requests.post(
            get_bucket_uri, json=params, headers=self._get_auth_headers()
        )
        bucket_info = create_bucket_response.content.decode("utf-8")
        bucket_info_json = json.load(bucket_info)  # pyright: ignore

        return bucket_info_json.name

    """
        Download a file from a bucket.

        :param bucket_name:
        :param key: storage source filepath
        :param filepath: local destination filepath
    """

    def download(self, bucket_name: str, key: str, filepath: str) -> None:
        pass

    """
        Upload a file to a bucket with by passing caching.
        Useful for uploading code package to storage (when required).

        :param bucket_name:
        :param filepath: local source filepath
        :param key: storage destination filepath
    """

    def upload(self, bucket_name: str, filepath: str, key: str):
        pass

    """
        Retrieves list of files in a bucket.

        :param bucket_name:
        :return: list of files in a given bucket
    """

    def list_bucket(self, bucket_name: str, prefix: str = "") -> List[str]:
        pass

    def list_buckets(self, bucket_name: Optional[str] = None) -> List[str]:
        pass

    def exists_bucket(self, bucket_name: str) -> bool:
        pass

    def clean_bucket(self, bucket_name: str):
        pass

    def remove_bucket(self, bucket: str):
        pass

    """
        Allocate a set of input/output buckets for the benchmark.
        The routine checks the cache first to verify that buckets have not
        been allocated first.

        :param benchmark: benchmark name
        :param buckets: number of input and number of output buckets
    """

    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        pass

    """
        Download all files in a storage bucket.
        Warning: assumes flat directory in a bucket! Does not handle bucket files
        with directory marks in a name, e.g. 'dir1/dir2/file'
    """

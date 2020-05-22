import logging
import uuid
from typing import List, Tuple

import boto3

from sebs.cache import Cache
from ..faas.storage import PersistentStorage


class S3(PersistentStorage):
    cached = False
    input_buckets: List[str] = []
    request_input_buckets = 0
    input_buckets_files: List[str] = []
    output_buckets: List[str] = []
    request_output_buckets = 0
    replace_existing = False

    def __init__(
        self, cache_client: Cache, location, access_key, secret_key, replace_existing
    ):
        self.client = boto3.client(
            "s3",
            region_name=location,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self.cache_client = cache_client
        self.replace_existing = replace_existing

    def input(self):  # noqa: A003
        return self.input_buckets

    def output(self):
        return self.output_buckets

    def create_bucket(self, name, buckets=None):
        found_bucket = False
        if buckets:
            for b in buckets:
                existing_bucket_name = b["Name"]
                if name in existing_bucket_name:
                    found_bucket = True
                    break
        # none found, create
        if not found_bucket:
            random_name = str(uuid.uuid4())[0:16]
            bucket_name = "{}-{}".format(name, random_name)
            self.client.create_bucket(Bucket=bucket_name)
            logging.info("Created bucket {}".format(bucket_name))
            return bucket_name
        else:
            logging.info(
                "Bucket {} for {} already exists, skipping.".format(
                    existing_bucket_name, name
                )
            )
            return existing_bucket_name

    def add_input_bucket(self, name: str) -> Tuple[str, int]:

        idx = self.request_input_buckets
        self.request_input_buckets += 1
        name = "{}-{}-input".format(name, idx)
        # there's cached bucket we could use
        for bucket in self.input_buckets:
            if name in bucket:
                return bucket, idx
        # otherwise add one
        bucket_name = self.create_bucket(name)
        self.input_buckets.append(bucket_name)
        return bucket_name, idx

    """
        :param cache: if true then bucket will be counted and mentioned in cache
    """

    def add_output_bucket(self, name: str, suffix: str = "output", cache: bool = True):

        idx = self.request_input_buckets
        name = "{}-{}-{}".format(name, idx + 1, suffix)
        if cache:
            self.request_input_buckets += 1
            # there's cached bucket we could use
            for bucket in self.input_buckets:
                if name in bucket:
                    return bucket, idx
        # otherwise add one
        bucket_name = self.create_bucket(name)
        if cache:
            self.input_buckets.append(bucket_name)
        return bucket_name

    def create_buckets(self, benchmark, buckets, cached_buckets):

        self.request_input_buckets = buckets[0]
        self.request_output_buckets = buckets[1]
        if cached_buckets:
            self.input_buckets = cached_buckets["buckets"]["input"]
            for bucket in self.input_buckets:
                self.input_buckets_files.append(
                    self.client.list_objects_v2(Bucket=self.input_buckets[-1])
                )
            self.output_buckets = cached_buckets["buckets"]["output"]
            for bucket in self.output_buckets:
                objects = self.client.list_objects_v2(Bucket=bucket)
                if "Contents" in objects:
                    objects = [{"Key": obj["Key"]} for obj in objects["Contents"]]
                    self.client.delete_objects(
                        Bucket=bucket, Delete={"Objects": objects}
                    )
            self.cached = True
            logging.info(
                "Using cached storage input buckets {}".format(self.input_buckets)
            )
            logging.info(
                "Using cached storage output buckets {}".format(self.output_buckets)
            )
        else:
            s3_buckets = self.client.list_buckets()["Buckets"]
            for i in range(0, buckets[0]):
                self.input_buckets.append(
                    self.create_bucket("{}-{}-input".format(benchmark, i), s3_buckets)
                )
                self.input_buckets_files.append(
                    self.client.list_objects_v2(Bucket=self.input_buckets[-1])
                )
            for i in range(0, buckets[1]):
                self.output_buckets.append(
                    self.create_bucket("{}-{}-output".format(benchmark, i), s3_buckets)
                )

    def uploader_func(self, bucket_idx, file, filepath):
        # Skip upload when using cached buckets and not updating storage.
        if self.cached and not self.replace_existing:
            return
        bucket_name = self.input_buckets[bucket_idx]
        if not self.replace_existing:
            if "Contents" in self.input_buckets_files[bucket_idx]:
                for f in self.input_buckets_files[bucket_idx]["Contents"]:
                    f_name = f["Key"]
                    if file == f_name:
                        logging.info(
                            "Skipping upload of {} to {}".format(filepath, bucket_name)
                        )
                        return
        bucket_name = self.input_buckets[bucket_idx]
        self.upload(bucket_name, file, filepath)

    """
        Upload without any caching. Useful for uploading code package to S3.
    """

    def upload(self, bucket_name: str, file: str, filepath: str):
        logging.info("Upload {} to {}".format(filepath, bucket_name))
        self.client.upload_file(filepath, bucket_name, file)

    """
        Download file from bucket.

        :param bucket_name:
        :param file:
        :param filepath:
    """

    def download(self, bucket_name: str, file: str, filepath: str):
        logging.info("Download {}:{} to {}".format(bucket_name, file, filepath))
        self.client.download_file(Bucket=bucket_name, Key=file, Filename=filepath)

    """
        Return list of files in a bucket.

        :param bucket_name:
        :return: list of file names. empty if bucket empty
    """

    def list_bucket(self, bucket_name: str):
        objects = self.client.list_objects_v2(Bucket=bucket_name)
        if "Contents" in objects:
            objects = [obj["Key"] for obj in objects["Contents"]]
        else:
            objects = []
        return objects

    def allocate_buckets(self, benchmark: str, buckets: Tuple[int, int]):
        self.create_buckets(
            benchmark, buckets, self.cache_client.get_storage_config("aws", benchmark),
        )

    # def download_results(self, result_dir):
    #    result_dir = os.path.join(result_dir, 'storage_output')
    #    for bucket in self.output_buckets:
    #        objects = self.connection.list_objects_v2(bucket)
    #        objects = [obj.object_name for obj in objects]
    #        for obj in objects:
    #            self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))
    #

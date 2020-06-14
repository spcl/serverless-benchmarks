import logging
import uuid
from typing import List, Tuple

from google.cloud import storage as gcp_storage

from ..faas.storage import PersistentStorage


class GCPStorage(PersistentStorage):
    cached: False
    input_buckets: List[str] = []
    output_buckets: List[str] = []
    input_buckets_files: []
    request_input_buckets: 0
    request_output_buckets: 0

    def __init__(self, replace_existing):
        self.replace_existing = replace_existing
        self.client = gcp_storage.Client()

    def input(self) -> List[str]:
        return self.input_buckets
    """
        Add an input bucket or retrieve an existing one.
        Bucket name format: name-idx-input
        :param name: bucket name
        :return: bucket name and index
    """

    def add_input_bucket(self, name: str) -> Tuple[str, int]:
        idx = self.request_input_buckets

        # TODO Do we want to increment that when the cache is used?
        self.request_input_buckets += 1
        name = '{}-{}-input'.format(name, idx)
        for bucket in self.input_buckets:
            if name in bucket:
                return bucket, idx
        bucket_name = self.create_bucket(name)
        self.input_buckets.append(bucket_name)

        # TODO idx is never used
        return bucket_name, idx

    """
        :return: list of output buckets defined in the storage
    """

    def output(self) -> List[str]:
        # return self.output()
        return self.output_buckets

    def create_bucket(self, name, buckets=None):
        found_bucket = False
        if buckets:
            for b in buckets:
                existing_bucket_name = b.name
                if name in existing_bucket_name:
                    found_bucket = True
                    break

        if not found_bucket:
            random_name = str(uuid.uuid4())[0:16]
            bucket_name = '{}-{}'.format(name, random_name).replace(".", "_")
            self.client.create_bucket(bucket_name)
            logging.info('Created bucket {}'.format(bucket_name))
            return bucket_name
        else:
            logging.info('Bucket {} for {} already exists, skipping.'.format(existing_bucket_name, name))
            return existing_bucket_name

    def download(self, bucket_name: str, file: str, filepath: str) -> None:
        logging.info('Download {}:{} to {}'.format(bucket_name, file, filepath))
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(file)
        blob.download_to_filename(filepath)

    def upload(self, bucket_name: str, file: str, filepath: str):
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(file)
        blob.upload_from_filename(filepath)

    """
        :param bucket_name:
        :return: list of files in a given bucket
    """

    #for sure ??? method add_output_bucket here?
    def list_bucket(self, bucket_name: str, suffix='output') -> List[str]:
        name = '{}-{}'.format(bucket_name, suffix)
        bucket_name = self.create_bucket(name)
        return bucket_name


    #cached_buckets? ...
    def allocate_buckets(self, benchmark: str, buckets: Tuple[int, int], cached_buckets = None):
        self.request_input_buckets = buckets[0]
        self.request_output_buckets = buckets[1]
        if cached_buckets:
            self.input_buckets = cached_buckets['buckets']['input']
            for bucket_name in self.input_buckets:
                self.input_buckets_files.append(list(self.client.bucket(bucket_name).list_blobs()))

            self.output_buckets = cached_buckets['buckets']['output']
            for bucket_name in self.output_buckets:
                for blob in self.client.bucket(bucket_name).list_blobs():
                    blob.delete()

            self.cached = True
            logging.info('Using cached storage input containers {}'.format(self.input_buckets))
            logging.info('Using cached storage output containers {}'.format(self.output_buckets))

        else:
            gcp_buckets = list(self.client.list_buckets())
            for i in range(buckets[0]):
                self.input_buckets.append(self.create_bucket('{}-{}-input'.format(benchmark, i), gcp_buckets))

                # TODO why in AWS and Azure only one (the last) bucket is used?
                self.input_buckets_files.append(list(self.client.bucket(self.input_buckets[i]).list_blobs()))

            for i in range(buckets[1]):
                self.output_buckets.append(self.create_bucket('{}-{}-output'.format(benchmark, i), gcp_buckets))

    def uploader_func(self, bucket_idx: int, file: str, filepath: str) -> None:
        if self.cached and not self.replace_existing:
            return
        bucket_name = self.input_buckets[bucket_idx]
        if not self.replace_existing:
            for blob in self.input_buckets_files[bucket_idx]:
                if file == blob.name:
                    logging.info('Skipping upload of {} to {}'.format(filepath, bucket_name))
                    return
        bucket_name = self.input_buckets[bucket_idx]
        self.upload(bucket_name, file, filepath)



from google.cloud import storage as gcp_storage
import google.auth.credentials.Credentials
import google.auth.credentials.AnonymousCredentials
import os
import time
import uuid

class storage:

    client = None
    input_buckets = []
    output_buckets = []
    input_buckets_files = []
    request_input_buckets = 0
    request_output_buckets = 0


    def __init__(self, location, access_key, replace_existing):
        self.replace_existing = replace_existing
        self.location = location
        self.client = gcp_storage.Client(credentials=AnonymousCredentials(token=access_key))

    def input(self):
        return self.input_buckets

    def output(self):
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
            bucket_name = '{}-{}'.format(name, random_name)
            self.client.create_bucket(bucket_name)
            logging.info('Created bucket {}'.format(bucket_name))
            return bucket_name
        else:
            logging.info('Bucket {} for {} already exists, skipping.'.format(existing_bucket_name, name))
            return existing_bucket_name

    def add_input_bucket(self, name):
        idx = self.request_input_buckets

        #TODO Do we want to increment that when the cache is used?
        self.request_input_buckets += 1
        name = '{}-{}-input'.format(name, idx)
        for bucket in self.input_buckets:
            if name in bucket:
                return bucket, idx
        bucket_name = self.create_bucket(name)
        self.input_buckets.append(bucket_name)

        #TODO idx is never used
        return bucket_name, idx


    #TODO Should we return with idx or not (in AWS there are two possible returns)
    def add_output_bucket(self, name, suffix="output"):
        name = '{}-{}'.format(name, suffix)
        bucket_name = self.create_bucket(name)
        return bucket_name


    def create_buckets(self, benchmark, buckets, cached_buckets):
        self.request_input_buckets = buckets[0]
        self.request_output_buckets = buckets[1]
        if cached_buckets:
            self.input_buckets = cached_buckets['buckets']['input']
            for bucket_name in self.input_buckets:
                self.input_buckets_files.appned(self.client.bucket(bucket_name).list_blobs())

            self.output_buckets = cached_buckets['buckets']['output']
            for bucket_name in self.output_buckets:
                for blob in self.client.bucket(bucket_name).list_blobs():
                    blob.delete()

            self.cached = True
            logging.info('Using cached storage input containers {}'.format(self.input_containers))
            logging.info('Using cached storage output containers {}'.format(self.output_containers))

        else:
            gcp_buckets = self.client.list_buckets()
            for i in range(buckets[0]):
                self.input_buckets.append(self.create_bucket('{}-{}-input'.format(benchmark, i), gcp_buckets))

                # TODO why in AWS and Azure only one (the last) bucket is used?
                self.input_bucket_files.append(self.client.bucket(self.input_buckets[i]).list_blobs())

            for i in range(buckets[1]):
                self.output_buckets.append(self.create_bucket('{}-{}-output'.format(benchmark, i), gcp_buckets))


    def uploader_func(self, bucket_idx, file, filepath):
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

    def upload(self, bucket_name, file, filepath):
        logging.info('Upload {} to {}'.format(filepath, bucket_name))
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(file)
        blob.upload_from_filename(filepath)


    def download(self, bucket_name, file, filepath):
        logging.info('Download {}:{} to {}'.format(bucket_name, file, filepath))
        bucket_instance = self.client.bucket(bucket_name)
        blob = bucket_instance.blob(file)
        blob.download_to_filename(filepath)

    def list_buckets(self, bucket_name):
        blobs = self.client.bucket(bucket_name).list_blobs()
        return [blob.name for blob in blobs]




class gcp:

    def __init__(self):
        pass

    def get_storage(self, benchmark, buckets, replace_existing):
        pass

    def package_code(self, dir, benchmark):
        pass

    def create_function(self, code_package, experiment_config):
        pass

    def prepare_experiment(self, benchmark):
        pass

    def invoke_sync(self, name: str, payload: dict):
        pass

    def invoke_async(self, name: str, payload: dict):
        pass

    def shutdown(self):
        pass

    def download_metrics(self, function_name: str, deployment_config: dict,
                         start_time: int, end_time: int, requests: dict):
        pass

    def create_function_copies(self, function_names: List[str], api_name: str, memory: int, timeout: int,
                               code_package: CodePackage, experiment_config: dict, api_id: str = None):
        pass



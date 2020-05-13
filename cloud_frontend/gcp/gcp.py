
from google.cloud import storage as gcp_storage
import google.auth.credentials.Credentials
from google.auth.credentials import AnonymousCredentials
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

    access_key = None

    def __init__(self, cache_client, config, language, docker_client):
        self.config = config
        self.language = language
        self.docker_client = docker_client
        self.cache_client = cache_client

    def configure_credentials(self):
        if self.access_key is None:
            if 'secrets' in self.config:
                self.access_key = self.config['secrets']['access_key']
            elif 'GCP_ACCESS_KEY' in os.environ:
                self.access_key = os.environ['GCP_ACCESS_KEY']
                self.cache_client.update_config(val=self.access_key, keys=['gcp', 'secrets', 'access_key'])
            else:
                raise RuntimeError("GCP login credentials are missing!")


    def get_storage(self, benchmark=None, buckets=None, replace_existing=False):
        self.configure_credentials()
        self.location = self.config['config']['region']
        self.storage = storage(self.location, self.access_key, replace_existing)
        if benchmark and buckets:
            self.storage.create_buckets(benchmark, buckets, self.cache_client.get_storage_config('gcp', benchmark))
        return self.storage

    """

    - main.py/index.js (handler.py/js)
    - function
      - function.py/js
      - storage.py/js
      - resources
    """
    def package_code(self, dir, benchmark):

        CONFIG_FILES = {
            'python': ['handler.py', 'requirements.txt', '.python_packages'],
            'nodejs': ['handler.js', 'package.json', 'node_modules']
        }
        HANDLER = {
            'python': ('handler.py', 'main.py'),
            'nodejs': ('handler.js', 'index.js')
        }

        package_config = CONFIG_FILES[self.language]
        function_dir = os.path.join(dir, 'function')
        os.makedirs(function_dir)
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, function_dir)

        cur_dir = os.getcwd()
        os.chdir(dir)
        old_name, new_name = HANDLER[self.language]
        shutil.move(old_name, new_name)

        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True)
        benchmark_archive = "{}.zip".format(os.path.join(dir, benchmark))
        logging.info('Created {} archive'.format(benchmark_archive))

        shutil.move(new_name, old_name)
        os.chdir(cur_dir)
        return os.path.join(dir, "{}.zip".format(benchmark))


    def create_function(self, code_package, experiment_config):

        benchmark = code_package.benchmark
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info('Using cached function {fname} in {loc}'.format(
                fname=func_name,
                loc=code_location
            ))
            return func_name

        elif code_package.is_cached:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            package = self.package_code(code_location, code_package.benchmark)
            code_size = CodePackage.directory_size(code_location)
            self.update_function(benchmark, func_name, package, timeout, memory)

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function('gcp', benchmark, self.language, package, cached_cfg)

            logging.info("Updating cached function {fname} in {loc}".format(
                fname=func_name,
                loc=code_location
            ))

            return func_name
        else:

            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]
            code_size = CodePackage.directory_size(code_location)

            func_name = '{}-{}-{}'.format(benchmark, self.language, memory)
            func_name = func_name.replace('-', '_')
            func_name = func_name.replace('.', '_')

            package = self.package_code(code_location, code_package.benchmark)

            code_package_name = os.path.basename(package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package_name, package)
            logging.info('Uploading function {} code to {}'.format(func_name, bucket))
            blob = self.storage.client.bucket(bucket).blob(code_package_name)
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(minutes=15),
                method="GET",  # TODO I'm not sure which method to put here
            )

            # TODO check if the function exists
            # https://cloud.google.com/functions/docs/reference/rest/v1/projects.locations.functions/get
            if False:
                update_function_url = "https://cloudfunctions.googleapis.com/v1/{function.name}"
                payload = {
                    "name": func_name,
                    "entrypoint": "handler",
                    "availableMemoryMb": memory,
                    "timeout": timeout,
                    "sourceArchiveUrl": signed_url  # TODO check if the url starts with "gs://"
                }
                requests.request(method="POST", url=update_function_url, payload=payload)
                logging.info('Updating AWS code of function {} from {}'.format(func_name, code_package))
            else:
                create_function_url = "https://cloudfunctions.googleapis.com/v1/{location}/functions".format(
                    location="" #TODO
                )

                # possible runtimes: https://cloud.google.com/sdk/gcloud/reference/functions/deploy#--runtime
                # TODO delete from docker images unnecessary python/nodejs versions

                language_runtime = self.config['config']['runtime'][self.language]
                payload = {
                    "name": func_name,
                    "entrypoint": "handler",
                    "runtime": self.language + language_runtime.replace(".", ""),
                    "availableMemoryMb": memory,
                    "timeout": timeout,
                    "sourceArchiveUrl": signed_url #TODO check if the url starts with "gs://"
                }

                requests.request(method="POST", url=create_function_url, payload=payload)
                invoke_url = "https://YOUR_REGION-YOUR_PROJECT_ID.cloudfunctions.net/{function_name}".format(
                    function_name=func_name
                )

            self.cache_client.add_function(
                deployment="gcp",
                benchmark=benchmark,
                language=self.language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": language_runtime,
                    'role': self.config['config']['lambda-role'],
                    'memory': memory,
                    'timeout': timeout,
                    'hash': code_package.hash,
                    'url': invoke_url
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets
                    }
                }
            )
            return func_name

    def prepare_experiment(self, benchmark):
        logs_bucket = self.storage.add_output_bucket(benchmark, suffix='logs')
        return logs_bucket

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



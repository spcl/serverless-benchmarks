from googleapiclient.discovery import build
from google.cloud import storage as gcp_storage
import os
import time
import uuid
from typing import Tuple, List
from CodePackage import CodePackage
import shutil
from scripts.experiments_utils import *
import datetime

class storage:

    client = None
    input_buckets = []
    output_buckets = []
    input_buckets_files = []
    request_input_buckets = 0
    request_output_buckets = 0

    def __init__(self, replace_existing):
        self.replace_existing = replace_existing
        self.client = gcp_storage.Client()

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
            bucket_name = '{}-{}'.format(name, random_name).replace(".", "_")
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
                self.input_buckets_files.append(self.client.bucket(bucket_name).list_blobs())

            self.output_buckets = cached_buckets['buckets']['output']
            for bucket_name in self.output_buckets:
                for blob in self.client.bucket(bucket_name).list_blobs():
                    blob.delete()

            self.cached = True
            logging.info('Using cached storage input containers {}'.format(self.input_buckets))
            logging.info('Using cached storage output containers {}'.format(self.output_buckets))

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

    def __init__(self, cache_client, config, language, docker_client):
        self.config = config
        self.language = language
        self.docker_client = docker_client
        self.cache_client = cache_client
        self.gcp_credentials = None
        self.storage = None

        self.project_name = None
        self.location = None

        self.configure_credentials()
        self.function_client = build("cloudfunctions", "v1")

    def configure_credentials(self):
        if self.gcp_credentials is None:
            if 'secrets' in self.config:
                self.gcp_credentials = self.config['secrets']['gcp_credentials']
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.gcp_credentials
            elif "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
                self.gcp_credentials = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
                self.cache_client.update_config(val=self.gcp_credentials, keys=['gcp', 'secrets', 'gcp_credentials'])
            else:
                raise RuntimeError("GCP login credentials are missing!")

    def get_storage(self, benchmark=None, buckets=None, replace_existing=False):
        self.storage = storage(replace_existing)
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
        self.location = experiment_config["experiments"]["deployment"]["config"]["region"]
        self.project_name = experiment_config["experiments"]["deployment"]["config"]["project_name"]
        project_name = self.project_name
        location = self.location

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

            func_name = 'foo_{}-{}-{}'.format(benchmark, self.language, memory)
            func_name = func_name.replace('-', '_')
            func_name = func_name.replace('.', '_')

            package = self.package_code(code_location, code_package.benchmark)

            code_package_name = os.path.basename(package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package_name, package)
            logging.info('Uploading function {} code to {}'.format(func_name, bucket))
            blob = self.storage.client.bucket(bucket).blob(code_package_name)
            # signed_url = blob.generate_signed_url(
            #     version="v4",
            #     expiration=datetime.timedelta(minutes=15),
            #     method="GET",  # TODO I'm not sure which method to put here
            # )

            print("Experiment config: ", experiment_config)
            req = self.function_client.projects().locations().functions().list(parent="projects/{project_name}/locations/{location}"
                                                                   .format(project_name=project_name, location=location))
            res = req.execute()

            full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(project_name=project_name, location=location, func_name=func_name)
            if "functions" in res.keys() and full_func_name in [f["name"] for f in res["functions"]]:
                language_runtime = str(self.config['config']['runtime'][self.language])
                req = self.function_client.projects().locations().functions().patch(
                    name=full_func_name,
                    body={
                        "name": full_func_name,
                        "entryPoint": "handler",
                        "runtime": self.language + language_runtime.replace(".", ""),
                        "availableMemoryMb": memory,
                        "timeout": str(timeout) + "s",
                        "httpsTrigger": {},
                        "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
                    })
                res = req.execute()
                print("response:", res)
                logging.info('Updating AWS code of function {} from {}'.format(func_name, code_package))
            else:

                language_runtime = str(self.config['config']['runtime'][self.language])
                print("language runtime: ", self.language + language_runtime.replace(".", ""))
                req = self.function_client.projects().locations().functions().create(
                    location="projects/{project_name}/locations/{location}".format(project_name=project_name, location=location),
                    body={
                        "name": full_func_name,
                        "entryPoint": "handler",
                        "runtime": self.language + language_runtime.replace(".", ""),
                        "availableMemoryMb": memory,
                        "timeout": str(timeout) + "s",
                        "httpsTrigger": {},
                        "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
                    }
                )
                print("request: ", req)
                res = req.execute()
                print("response:", res)

            our_function_req = self.function_client.projects().locations().functions().get(name=full_func_name)
            res = our_function_req.execute()
            invoke_url = res["httpsTrigger"]["url"]
            print("RESPONSE: ", res)

            self.cache_client.add_function(
                deployment="gcp",
                benchmark=benchmark,
                language=self.language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": self.config['config']['runtime'][self.language],
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
        full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(
            project_name=self.project_name, location=self.location, func_name=name)
        print(payload)
        payload = json.dumps(payload)
        print(payload)
        req = self.function_client.projects().locations().functions().call(
            name=full_func_name,
            body={
                "data": payload
            }
        )
        begin = datetime.datetime.now()
        res = req.execute()
        end = datetime.datetime.now()

        print("RES: ", res)

        if "error" in res.keys() and res["error"] != "":
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload))
            raise RuntimeError()

        print("Result", res["result"])
        return {"return": res["result"], "client_time": (end - begin) / datetime.timedelta(microseconds=1)}

    def invoke_async(self, name: str, payload: dict):
        print("Nope")

    def shutdown(self):
        pass

    def download_metrics(self, function_name: str, deployment_config: dict,
                         start_time: int, end_time: int, requests: dict):
        pass

    def create_function_copies(self, function_names: List[str], api_name: str, memory: int, timeout: int,
                               code_package: CodePackage, experiment_config: dict, api_id: str = None):
        pass



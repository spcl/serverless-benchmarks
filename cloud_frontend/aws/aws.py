
import base64
import datetime
import json
import logging
import os
import time
import uuid

import boto3

from typing import Tuple

from scripts.experiments_utils import *
from CodePackage import CodePackage

class aws:
    client = None
    logs_client = None
    cache_client = None
    docker_client = None
    config = None
    storage = None
    language = None
    cached = False

    # AWS credentials
    access_key = None
    secret_key = None

    class s3:
        cached = False
        client = None
        input_buckets = []
        request_input_buckets = 0
        input_buckets_files = []
        output_buckets = []
        request_output_buckets = 0
        replace_existing = False

        def __init__(self, location, access_key, secret_key, replace_existing):
            self.client = boto3.client(
                    's3',
                    region_name=location,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key
                )
            self.replace_existing = replace_existing

        def input(self):
            return self.input_buckets

        def output(self):
            return self.output_buckets

        def create_bucket(self, name, buckets=None):
            found_bucket = False
            if buckets:
                for b in buckets:
                    existing_bucket_name = b['Name']
                    if name in existing_bucket_name:
                        found_bucket = True
                        break
            # none found, create
            if not found_bucket:
                random_name = str(uuid.uuid4())[0:16]
                bucket_name = '{}-{}'.format(name, random_name)
                self.client.create_bucket(Bucket=bucket_name)
                logging.info('Created bucket {}'.format(bucket_name))
                return bucket_name
            else:
                logging.info('Bucket {} for {} already exists, skipping.'.format(existing_bucket_name, name))
                return existing_bucket_name

        def add_input_bucket(self, name):

            idx = self.request_input_buckets
            self.request_input_buckets += 1
            name = '{}-{}-input'.format(name, idx)
            # there's cached bucket we could use
            for bucket in self.input_buckets:
                if name in bucket:
                    return bucket, idx
            # otherwise add one
            bucket_name = self.create_bucket(name)
            self.input_buckets.append(bucket_name)
            return bucket_name, idx

        '''
            :param cache: if true then bucket will be counted and mentioned in cache
        '''
        def add_output_bucket(self, name :str, suffix: str='output', cache: bool=True):

            idx = self.request_input_buckets
            name = '{}-{}-{}'.format(name, idx + 1, suffix)
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
                self.input_buckets = cached_buckets['buckets']['input']
                for bucket in self.input_buckets:
                    self.input_buckets_files.append(
                        self.client.list_objects_v2(
                            Bucket=self.input_buckets[-1]
                        )
                    )
                self.output_buckets = cached_buckets['buckets']['output']
                for bucket in self.output_buckets:
                    objects = self.client.list_objects_v2(Bucket=bucket)
                    if 'Contents' in objects:
                        objects = [{'Key': obj['Key']} for obj in objects['Contents']]
                        self.client.delete_objects(
                                Bucket=bucket,
                                Delete={
                                    'Objects': objects
                                }
                        )
                self.cached = True
                logging.info('Using cached storage input buckets {}'.format(self.input_buckets))
                logging.info('Using cached storage output buckets {}'.format(self.output_buckets))
            else:
                s3_buckets = self.client.list_buckets()['Buckets']
                for i in range(0, buckets[0]):
                    self.input_buckets.append(
                        self.create_bucket(
                            '{}-{}-input'.format(benchmark, i),
                            s3_buckets
                        )
                    )
                    self.input_buckets_files.append(
                        self.client.list_objects_v2(
                            Bucket=self.input_buckets[-1]
                        )
                    )
                for i in range(0, buckets[1]):
                    self.output_buckets.append(
                        self.create_bucket(
                            '{}-{}-output'.format(benchmark, i),
                            s3_buckets
                        )
                    )

        def uploader_func(self, bucket_idx, file, filepath):
            # Skip upload when using cached buckets and not updating storage.
            if self.cached and not self.replace_existing:
                return
            bucket_name = self.input_buckets[bucket_idx]
            if not self.replace_existing:
                if 'Contents' in self.input_buckets_files[bucket_idx]:
                    for f in self.input_buckets_files[bucket_idx]['Contents']:
                        f_name = f['Key']
                        if file == f_name:
                            logging.info('Skipping upload of {} to {}'.format(filepath, bucket_name))
                            return
            bucket_name = self.input_buckets[bucket_idx]
            self.upload(bucket_name, file, filepath)

        '''
            Upload without any caching. Useful for uploading code package to S3.
        '''
        def upload(self, bucket_name :str, file :str, filepath :str):
            logging.info('Upload {} to {}'.format(filepath, bucket_name))
            self.client.upload_file(filepath, bucket_name, file)

        '''
            Download file from bucket.

            :param bucket_name:
            :param file:
            :param filepath:
        '''
        def download(self, bucket_name :str, file :str, filepath :str):
            logging.info('Download {}:{} to {}'.format(bucket_name, file, filepath))
            self.client.download_file(
                Bucket=bucket_name,
                Key=file,
                Filename=filepath
            )

        '''
            Return list of files in a bucket.

            :param bucket_name:
            :return: list of file names. empty if bucket empty
        '''
        def list_bucket(self, bucket_name :str):
            objects = self.client.list_objects_v2(Bucket=bucket_name)
            if 'Contents' in objects:
                objects = [obj['Key'] for obj in objects['Contents']]
            else:
                objects = []
            return objects

        #def download_results(self, result_dir):
        #    result_dir = os.path.join(result_dir, 'storage_output')
        #    for bucket in self.output_buckets:
        #        objects = self.connection.list_objects_v2(bucket)
        #        objects = [obj.object_name for obj in objects]
        #        for obj in objects:
        #            self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))
        #

    '''
        :param cache_client: Function cache instance
        :param config: Experiments config
        :param language: Programming language to use for functions
        :param docker_client: Docker instance
    '''
    def __init__(self, cache_client, config, language, docker_client):
        self.config = config
        self.language = language
        self.cache_client = cache_client
        self.docker_client = docker_client

    '''
        Parse AWS credentials passed in config or environment variables.
        Updates class properties.
    '''
    def configure_credentials(self):
        if self.access_key is None:
            # Verify we can log in
            # 1. Cached credentials
            # TODO: flag to update cache
            if 'secrets' in self.config['aws']:
                self.access_key = self.config['aws']['secrets']['access_key']
                self.secret_key = self.config['aws']['secrets']['secret_key']
            # 2. Environmental variables
            elif 'AWS_ACCESS_KEY_ID' in os.environ:
                self.access_key = os.environ['AWS_ACCESS_KEY_ID']
                self.secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
                # update
                self.cache_client.update_config(
                        val=self.access_key,
                        keys=['aws', 'secrets', 'access_key'])
                self.cache_client.update_config(
                        val=self.secret_key,
                        keys=['aws', 'secrets', 'secret_key'])
            else:
                raise RuntimeError('AWS login credentials are missing! Please set '
                        'up environmental variables AWS_ACCESS_KEY_ID and '
                        'AWS_SECRET_ACCESS_KEY')

    '''
        Start boto3 client for `client` AWS resource.

        :param resource: AWS resource to use
        :param code_package: not used
    '''
    def start(self, resource :str = 'lambda', code_package=None):

        self.configure_credentials()
        return boto3.client(resource,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.config['aws']['region'])

    def start_lambda(self):
        if not self.client:
            self.client = self.start('lambda')

    '''
        Create a client instance for cloud storage. When benchmark and buckets
        parameters are passed, then storage is initialized with required number
        of buckets. Buckets may be created or retrieved from cache.

        :param benchmark: benchmark name
        :param buckets: tuple of required input/output buckets
        :param replace_existing: when true, the existing files in cached buckets are replaced
        :return: storage client
    '''
    def get_storage(self, benchmark :str = None, buckets :Tuple[int, int] = None,
            replace_existing :bool = False):
        self.configure_credentials()
        self.storage = aws.s3(
                self.config['aws']['region'],
                access_key=self.access_key,
                secret_key=self.secret_key,
                replace_existing=replace_existing)
        if benchmark and buckets:
            self.storage.create_buckets(benchmark, buckets,
                    self.cache_client.get_storage_config('aws', benchmark)
            )
        return self.storage

    '''
        It would be sufficient to just pack the code and ship it as zip to AWS.
        However, to have a compatible function implementation across providers,
        we create a small module.
        Issue: relative imports in Python when using storage wrapper.
        Azure expects a relative import inside a module thus it's easier
        to always create a module.

        Structure:
        function
        - function.py
        - storage.py
        - resources
        handler.py

        dir: directory where code is located
        benchmark: benchmark name
    '''
    def package_code(self, dir :str, benchmark :str):

        CONFIG_FILES = {
            'python': ['handler.py', 'requirements.txt', '.python_packages'],
            'nodejs': ['handler.js', 'package.json', 'node_modules']
        }
        package_config = CONFIG_FILES[self.language]
        function_dir = os.path.join(dir, 'function')
        os.makedirs(function_dir)
        # move all files to 'function' except handler.py
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, function_dir)

        cur_dir = os.getcwd()
        os.chdir(dir)
        # create zip with hidden directory but without parent directory
        execute('zip -qu -r9 {}.zip * .'.format(benchmark), shell=True)
        benchmark_archive = '{}.zip'.format(os.path.join(dir, benchmark))
        logging.info('Created {} archive'.format(benchmark_archive))

        bytes_size = os.path.getsize(benchmark_archive)
        mbytes =  bytes_size / 1024.0 / 1024.0
        logging.info('Zip archive size {:2f} MB'.format(mbytes))
        os.chdir(cur_dir)
        return os.path.join(dir, '{}.zip'.format(benchmark)), bytes_size

    '''
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param benchmark_path: Path to benchmark code
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    '''
    def create_function(self, code_package: CodePackage, experiment_config :dict):

        benchmark = code_package.benchmark
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config['name']
            code_location = code_package.code_location
            logging.info('Using cached function {fname} in {loc}'.format(
                fname=func_name,
                loc=code_location
            ))
            return func_name
        elif code_package.is_cached:

            func_name = code_package.cached_config['name']
            code_location = code_package.code_location
            timeout = code_package.benchmark_config['timeout']
            memory = code_package.benchmark_config['memory']

            self.start_lambda()
            # Run AWS-specific part of building code.
            package, code_size = self.package_code(code_location, code_package.benchmark)
            package_body = open(package, 'rb').read()
            self.update_function(benchmark, func_name, package, code_size, timeout, memory)

            cached_cfg = code_package.cached_config
            cached_cfg['code_size'] = code_size
            cached_cfg['timeout'] = timeout
            cached_cfg['memory'] = memory
            cached_cfg['hash'] = code_package.hash()
            self.cache_client.update_function('aws', benchmark, self.language,
                    package, cached_cfg
            )

            logging.info('Updating cached function {fname} in {loc}'.format(
                fname=func_name,
                loc=code_location
            ))

            return func_name
        # no cached instance, create package and upload code
        else:

            func_name = code_package.function_name()
            code_location = code_package.code_location()
            timeout = code_package.benchmark_config['timeout']
            memory = code_package.benchmark_config['memory']

            self.start_lambda()

            # Create function name
            if not function_name:
                func_name = '{}-{}-{}'.format(benchmark, self.language, memory)
                # AWS Lambda does not allow hyphens in function names
                func_name = func_name.replace('-', '_')
                func_name = func_name.replace('.', '_')
            else:
                func_name = function_name

            # Run AWS-specific part of building code.
            package, code_size  = self.package_code(code_location, code_package.benchmark())
            package_body = open(package, 'rb').read()

            # we can either check for exception or use list_functions
            # there's no API for test
            try:
                self.client.get_function(FunctionName=func_name)
                self.update_function(benchmark, func_name, code_package, code_size, timeout, memory)
            except self.client.exceptions.ResourceNotFoundException:
                logging.info('Creating function function {} from {}'.format(func_name, code_package))

                # TODO: create Lambda role
                # AWS Lambda limit on zip deployment size
                if code_size < 69905067:
                    code_body = open(code_package, 'rb').read()
                    code_config = {'ZipFile': code_body}
                # Upload code package to S3, then use it
                else:
                    code_package_name = os.path.basename(code_package)
                    bucket, idx = self.storage.add_input_bucket(benchmark)
                    self.storage.upload(bucket, code_package_name, code_package)
                    code_config = {'S3Bucket': bucket, 'S3Key': code_package_name}
                self.client.create_function(
                    FunctionName=func_name,
                    Runtime='{}{}'.format(self.language,self.config['experiments']['runtime']),
                    Handler='handler.handler',
                    Role=self.config['aws']['lambda-role'],
                    MemorySize=memory,
                    Timeout=timeout,
                    Code=code_config
                )

            self.cache_client.add_function(
                    deployment='aws',
                    benchmark=benchmark,
                    language=self.language,
                    code_package=package,
                    language_config={
                        'name': func_name,
                        'code_size': code_size,
                        'runtime': self.config['experiments']['runtime'],
                        'role': self.config['aws']['lambda-role'],
                        'memory': memory,
                        'timeout': timeout,
                        'hash': code_package.hash()
                    },
                    storage_config={
                        'buckets': {
                            'input': self.storage.input_buckets,
                            'output': self.storage.output_buckets
                        }
                    }
            )
            return func_name, code_size

    '''
        Update function code and configuration on AWS.

        :param benchmark: benchmark name
        :param name: function name
        :param code_package: path to code package
        :param code_size: size of code package in bytes
        :param timeout: function timeout in seconds
        :param memory: memory limit for function
    '''
    def update_function(self, benchmark :str, name :str, code_package :str,
            code_size :int, timeout :int, memory :int):
        # AWS Lambda limit on zip deployment
        if code_size < 69905067:
            code_body = open(code_package, 'rb').read()
            self.client.update_function_code(
                FunctionName=name,
                ZipFile=code_body
            )
        # Upload code package to S3, then update
        else:
            code_package_name = os.path.basename(code_package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package_name, code_package)
            self.client.update_function_code(
                FunctionName=name,
                S3Bucket=bucket,
                S3Key=code_package_name
            )
        # and update config
        self.client.update_function_configuration(
            FunctionName=name,
            Timeout=timeout,
            MemorySize=memory
        )
        logging.info('Updating AWS code of function {} from {}'.format(name, code_package))


    '''
        Prepare AWS resources to store experiment results.
        Allocate one bucket.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    '''
    def prepare_experiment(self, benchmark :str):
        logs_bucket = self.storage.add_output_bucket(benchmark, suffix='logs')
        return logs_bucket

    def invoke_sync(self, name :str, payload :dict):

        self.start_lambda()
        payload = json.dumps(payload).encode('utf-8')
        begin = datetime.datetime.now()
        ret = self.client.invoke(
            FunctionName=name,
            Payload=payload,
            LogType='Tail'
        )
        end = datetime.datetime.now()

        if ret['StatusCode'] != 200:
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload.decode('utf-8')))
            raise RuntimeError()
        if 'FunctionError' in ret:
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload.decode('utf-8')))
            raise RuntimeError()
        log = base64.b64decode(ret['LogResult'])
        vals = {}
        vals['aws'] = aws.parse_aws_report(log.decode('utf-8'))
        ret = json.loads(ret['Payload'].read().decode('utf-8'))
        vals['client_time'] = (end - begin) / datetime.timedelta(microseconds=1)
        vals['compute_time'] = ret['compute_time']
        vals['results_time'] = ret['results_time']
        vals['result'] = ret['result']
        return vals

    def invoke_async(self, name :str, payload :dict):

        ret = self.client.invoke(
            FunctionName=name,
            InvocationType='Event',
            Payload=payload,
            LogType='Tail'
        )
        if ret['StatusCode'] != 202:
            logging.error('Async invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload.decode('utf-8')))
            raise RuntimeError()

    '''
        Accepts AWS report after function invocation.
        Returns a dictionary filled with values with various metrics such as
        time, invocation time and memory consumed.

        :param log: decoded log from CloudWatch or from synchronuous invocation
        :return: dictionary with parsed values
    '''
    def parse_aws_report(log :str):
        aws_vals = {}
        for line in log.split('\t'):
            if not line.isspace():
                split = line.split(':')
                aws_vals[split[0]] = split[1].split()[0]
        return aws_vals

    def shutdown(self):
        pass

    def download_metrics(self, function_name :str, deployment_config :dict,
            start_time :int, end_time :int, requests :dict):

        self.configure_credentials()
        if not self.logs_client:
            self.logs_client = self.start('logs')

        query = self.logs_client.start_query(
            logGroupName='/aws/lambda/{}'.format(function_name),
            queryString="filter @message like /REPORT/",
            startTime=start_time,
            endTime=end_time
        )
        query_id = query['queryId']
        response = None

        while response == None or response['status'] == 'Running':
            logging.info('Waiting for AWS query to complete ...')
            time.sleep(1)
            response = self.logs_client.get_query_results(
                queryId=query_id
            )
        # results contain a list of matches
        # each match has multiple parts, we look at `@message` since this one
        # contains the report of invocation
        results = response['results']
        for val in results:
            for result_part in val:
                if result_part['field'] == '@message':
                    actual_result = aws.parse_aws_report(result_part['value'])
                    request_id = actual_result['REPORT RequestId']
                    if request_id not in requests:
                        logging.info('Found invocation {} without result in bucket!'.format(request_id))
                    del actual_result['REPORT RequestId']
                    requests[request_id]['aws'] = actual_result


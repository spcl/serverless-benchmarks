
import base64
import datetime
import json
import logging
import os
import uuid

import boto3

from scripts.experiments_utils import *

class aws:
    client = None
    cache_client = None
    docker_client = None
    config = None
    storage = None
    language = None
    cached = False

    class s3:
        cached = False
        client = None
        input_buckets = []
        input_buckets_files = []
        output_buckets = []
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

        def create_bucket(self, name, buckets):
            found_bucket = False
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

        def create_buckets(self, benchmark, buckets, cached_buckets):

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
                        objects = [obj['Key'] for obj in objects['Contents']]
                        for err in self.connection.remove_objects(bucket, objects):
                            logging.error("Deletion Error: {}".format(del_err))
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
            logging.info('Upload {} to {}'.format(filepath, bucket_name))
            self.client.upload_file(filepath, bucket_name, file)

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

    def start(self, code_package=None):

        if not self.client:
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
                        val=access_key,
                        keys=['aws', 'secrets', 'access_key'])
                self.cache_client.update_config(
                        val=secret_key,
                        keys=['aws', 'secrets', 'secret_key'])
            else:
                raise RuntimeError('AWS login credentials are missing! Please set '
                        'up environmental variables AWS_ACCESS_KEY_ID and '
                        'AWS_SECRET_ACCESS_KEY')

            self.client = boto3.client('lambda',
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.config['aws']['region'])

    def get_storage(self, benchmark, buckets, replace_existing=False):
        self.start()
        self.storage = aws.s3(
                self.config['aws']['region'],
                access_key=self.access_key,
                secret_key=self.secret_key,
                replace_existing=replace_existing)
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
        execute('zip -qur {}.zip * .'.format(benchmark), shell=True)
        logging.info('Created {}.zip archive'.format(os.path.join(dir, benchmark)))
        os.chdir(cur_dir)
        return os.path.join(dir, '{}.zip'.format(benchmark))

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
    def create_function(self, benchmark :str, benchmark_path :str,
            config :dict, function_name :str=''):

        func_name = None
        code_size = None
        cached_f = self.cache_client.get_function('aws', benchmark, self.language)

        # a) cached_instance and no update
        if cached_f is not None and not config['experiments']['update_code']:
            cached_cfg = cached_f[0]
            func_name = cached_cfg['name']
            code_size = cached_cfg['code_size']
            logging.info('Using cached function {} in {} of size {}'.format(
                func_name, cached_f[1], code_size
            ))
            return func_name, code_size
        # b) cached_instance, create package and update code
        elif cached_f is not None:

            cached_cfg = cached_f[0]
            func_name = cached_cfg['name']

            # Build code package
            code_package, code_size, benchmark_config = create_code_package(
                    self.docker_client, self, config['experiments'],
                    benchmark, benchmark_path
            )
            code_body = open(code_package, 'rb').read()
            logging.info('Updating cached function {} in {} of size {}'.format(
                func_name, code_package, code_size
            ))

            # Update function usign current benchmark config
            timeout = benchmark_config['timeout']
            memory = benchmark_config['memory']
            self.update_function(func_name, code_package, timeout, memory) 

            # update cache contents
            cached_cfg['code_size'] = code_size
            cached_cfg['timeout'] = timeout
            cached_cfg['memory'] = memory
            self.cache_client.update_function('aws', benchmark, self.language,
                    code_package, cached_cfg)
            
            return func_name, code_size
        # c) no cached instance, create package and upload code
        else:
            
            # Build code package
            code_package, code_size, benchmark_config = create_code_package(
                    self.docker_client, self, config['experiments'],
                    benchmark, benchmark_path
            )
            timeout = benchmark_config['timeout']
            memory = benchmark_config['memory']
            
            # Create function name
            if not function_name:
                func_name = '{}-{}-{}'.format(benchmark, self.language, memory)
                # AWS Lambda does not allow hyphens in function names
                func_name = func_name.replace('-', '_')
                func_name = func_name.replace('.', '_')
            else:
                func_name = function_name

            # we can either check for exception or use list_functions
            # there's no API for test
            try:
                self.client.get_function(FunctionName=func_name)
                self.update_function(func_name, code_package, timeout, memory)
            except self.client.exceptions.ResourceNotFoundException:
                logging.info('Creating function function {} from {}'.format(func_name, code_package))

                # TODO: create Lambda role
                code_body = open(code_package, 'rb').read()
                self.client.create_function(
                    FunctionName=func_name,
                    Runtime='{}{}'.format(self.language,self.config['experiments']['runtime']),
                    Handler='handler.handler',
                    Role=self.config['aws']['lambda-role'],
                    MemorySize=memory,
                    Timeout=timeout,
                    Code={'ZipFile': code_body}
                )

            self.cache_client.add_function(
                    deployment='aws',
                    benchmark=benchmark,
                    language=self.language,
                    code_package=code_package,
                    language_config={
                        'name': func_name,
                        'code_size': code_size,
                        'runtime': self.config['experiments']['runtime'],
                        'role': self.config['aws']['lambda-role'],
                        'memory': memory,
                        'timeout': timeout
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

        :param name: function name
        :param code_package: path to code package
        :param timeout: function timeout in seconds
        :param memory: memory limit for function
    '''
    def update_function(self, name :str, code_package :str, timeout :int, memory :int):
        self.start(code_package)
        code_body = open(code_package, 'rb').read()
        self.client.update_function_code(
            FunctionName=name,
            ZipFile=code_body
        )
        # and update config
        self.client.update_function_configuration(
            FunctionName=name,
            Timeout=timeout,
            MemorySize=memory
        )
        logging.info('Updating code of function {} from'.format(name, code_package))

    def invoke(self, name, payload):

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
        for line in log.decode('utf-8').split('\t'):
            if not line.isspace():
                split = line.split(':')
                vals[split[0]] = split[1].split()[0]
        ret = json.loads(ret['Payload'].read().decode('utf-8'))
        vals['function_time'] = ret['time']
        vals['client_time'] = (end - begin) / datetime.timedelta(microseconds=1)
        vals['message'] = ret['message']
        return vals

    def shutdown(self):
        pass


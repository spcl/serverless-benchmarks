
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
    config = None
    storage = None
    language = None

    class s3:
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
                    # TODO: replace existing bucket if param is passed
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

        def create_buckets(self, benchmark, buckets):
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
            bucket_name = self.input_buckets[bucket_idx]
            if not self.replace_existing:
                for f in self.input_buckets_files[bucket_idx]['Contents']:
                    f_name = f['Key']
                    if file == f_name:
                        logging.info('Skipping upload of {} to {}'.format(filepath, bucket_name))
                        return
            logging.info('Upload {} to {}'.format(filepath, bucket_name))
            self.client.upload_file(filepath, bucket_name, file)

        #def clean(self):
        #    for bucket in self.output_buckets:
        #        objects = self.connection.list_objects_v2(bucket)
        #        objects = [obj.object_name for obj in objects]
        #        for err in self.connection.remove_objects(bucket, objects):
        #            logging.error("Deletion Error: {}".format(del_err))

        #def download_results(self, result_dir):
        #    result_dir = os.path.join(result_dir, 'storage_output')
        #    for bucket in self.output_buckets:
        #        objects = self.connection.list_objects_v2(bucket)
        #        objects = [obj.object_name for obj in objects]
        #        for obj in objects:
        #            self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))
        #    

    def __init__(self, cache_client, config, language):
        self.config = config
        self.language = language
        self.cache_client = cache_client

        # Verify we can log in
        # 1. Cached credentials
        # TODO: flag to update cache
        if 'secrets' in config['aws']:
            self.access_key = config['aws']['secrets']['access_key']
            self.secret_key = config['aws']['secrets']['secret_key']
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
                region_name=config['experiments']['region'])

    def get_storage(self, benchmark, buckets, replace_existing=False):
        self.storage = aws.s3(
                self.config['experiments']['region'],
                access_key=self.access_key,
                secret_key=self.secret_key,
                replace_existing=replace_existing)
        self.storage.create_buckets(benchmark, buckets)
        return self.storage

    def package_code(self, dir, benchmark):
        cur_dir = os.getcwd()
        os.chdir(dir)
        # create zip
        execute('zip -qur {}.zip *'.format(benchmark), shell=True)
        logging.info('Created {}.zip archive'.format(os.path.join(dir, benchmark)))
        os.chdir(cur_dir)
        return os.path.join(dir, '{}.zip'.format(benchmark))

    def create_function(self, code_package, benchmark, memory=128, timeout=10):
        code_body = open(code_package, 'rb').read()
        func_name = '{}-{}-{}'.format(benchmark, self.language, memory)
        # AWS Lambda does not allow hyphens in function names
        func_name = func_name.replace('-', '_')
        func_name = func_name.replace('.', '_')
        # we can either check for exception or use list_functions
        # there's no API for test
        try:
            self.client.get_function(FunctionName=func_name)
            logging.info('Updating code of function {} from'.format(func_name, code_package))
            # if function exists, then update code
            self.client.update_function_code(
                FunctionName=func_name,
                ZipFile=code_body
            )
            # and update config
            self.client.update_function_configuration(
                FunctionName=func_name,
                Timeout=timeout,
                MemorySize=memory
            )
        except self.client.exceptions.ResourceNotFoundException:
            logging.info('Creating function function {} from {}'.format(func_name, code_package))
            # TODO: create Lambda role
            self.client.create_function(
                FunctionName=func_name,
                Runtime='{}{}'.format(self.language,self.config['experiments']['runtime']),
                Handler='handler.handler',
                Role=self.config['aws']['lambda-role'],
                MemorySize=memory,
                Timeout=timeout,
                Code={'ZipFile': code_body}
            )
        return func_name

    def invoke(self, name, payload):

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



import logging
import uuid

import boto3


class aws:
    client = None
    config = None
    storage = None
    language = None

    class s3:
        client = None
        input_buckets = []
        input_buckets_files = []
        output_buckets = []
        replace_existing = False

        def __init__(self, location, replace_existing):
            self.client = boto3.client('s3', region_name=location)
            self.replace_existing = replace_existing

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

    def __init__(self, config, language):
        self.config = config
        self.language = language
        self.client = boto3.client('lambda', region_name=config['region'])

    def get_storage(self, benchmark, buckets, replace_existing=False):
        self.storage = aws.s3(self.config['region'], replace_existing)
        self.storage.create_buckets(benchmark, buckets)
        return self.storage

    def create_function(self, code_package, benchmark, memory=128):
        code_body = open(code_package, 'rb').read()
        func_name = '{}-{}-{}'.format(benchmark, self.language, memory)
        # AWS Lambda does not allow hyphens in function names
        func_name = func_name.replace('-', '_')
        func_name = func_name.replace('.', '_')
        # we can either check for exception or use list_functions
        # there's no API for test
        try:
            self.client.get_function(FunctionName=func_name)
            # if function exists, then update code
            self.client.update_function_code(
                FunctionName=func_name,
                ZipFile=code_body
            )
            # and config TODO
        except self.client.exceptions.ResourceNotFoundException:
            self.client.create_function(
                FunctionName=func_name,
                Runtime=self.config['runtime'][self.language],
                Handler='handler.handler',
                Role=self.config['lambda-role'],
                MemorySize=memory,
                Code={'ZipFile': code_body}
            )
        return func_name

    def invoke(self, name, payload):
        ret = self.client.invoke(
            FunctionName=name,
            Payload=payload
        )
        if ret['StatusCode'] != 200:
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload.decode('utf-8')))
            raise RuntimeError()
        if 'FunctionError' in ret:
            logging.error('Invocation of {} failed!'.format(name))
            logging.error('Input: {}'.format(payload.decode('utf-8')))
            raise RuntimeError()
        ret = ret['Payload'].read().decode('utf-8')
        exec_time = ret['time']
        message = ret['message']

    #class s3:
    #    storage_container = None
    #    input_buckets = []
    #    output_buckets = []
    #    port = 9000
    #    location = 'us-east-1'
    #    connection = None


    #    def __init__(self, client, buckets):
    #        if buckets[0] + buckets[1] > 0:
    #            self.start()
    #            self.connection = self.get_connection()
    #            for i in range(0, buckets[0]):
    #                self.input_buckets.append(
    #                        self.create_bucket('{}-{}-input'.format(benchmark, size)))
    #            for i in range(0, buckets[1]):
    #                self.output_buckets.append(
    #                        self.create_bucket('{}-{}-output'.format(benchmark, size)))
    #             
    #    def start(self):
    #        self.access_key = secrets.token_urlsafe(32)
    #        self.secret_key = secrets.token_hex(32)
    #        print('Starting minio instance at localhost:{}'.format(self.port), file=output_file)
    #        print('ACCESS_KEY', self.access_key, file=output_file)
    #        print('SECRET_KEY', self.secret_key, file=output_file)
    #        self.storage_container = client.containers.run(
    #            'minio/minio',
    #            command='server /data',
    #            ports={str(self.port): self.port},
    #            environment={
    #                'MINIO_ACCESS_KEY' : self.access_key,
    #                'MINIO_SECRET_KEY' : self.secret_key
    #            },
    #            remove=True,
    #            stdout=True, stderr=True,
    #            detach=True
    #        )

    #    def stop(self):
    #        if self.storage_container is not None:
    #            print('Stopping minio instance at localhost:{}'.format(self.port),file=output_file)
    #            self.storage_container.stop()

    #    def get_connection(self):
    #        return minio.Minio('localhost:{}'.format(self.port),
    #                access_key=self.access_key,
    #                secret_key=self.secret_key,
    #                secure=False)

    #    def config_to_json(self):
    #        if self.storage_container is not None:
    #            return {
    #                    'address': 'localhost:{}'.format(self.port),
    #                    'secret_key': self.secret_key,
    #                    'access_key': self.access_key,
    #                    'input': self.input_buckets,
    #                    'output': self.output_buckets
    #                }
    #        else:
    #            return {}

    #    def create_bucket(self, name):
    #        # minio has limit of bucket name to 16 characters
    #        bucket_name = '{}-{}'.format(name, str(uuid.uuid4())[0:16])
    #        try:
    #            self.connection.make_bucket(bucket_name, location=self.location)
    #            print('Created bucket {}'.format(bucket_name),file=output_file)
    #            return bucket_name
    #        except (minio.error.BucketAlreadyOwnedByYou, minio.error.BucketAlreadyExists, minio.error.ResponseError) as err:
    #            print('Bucket creation failed!')
    #            print(err)
    #            # rethrow
    #            raise err

    #    def uploader_func(self, bucket, file, filepath):
    #        try:
    #            self.connection.fput_object(bucket, file, filepath)
    #        except minio.error.ResponseError as err:
    #            print('Upload failed!')
    #            print(err)
    #            raise(err)

    #    def clean(self):
    #        for bucket in self.output_buckets:
    #            objects = self.connection.list_objects_v2(bucket)
    #            objects = [obj.object_name for obj in objects]
    #            for err in self.connection.remove_objects(bucket, objects):
    #                print("Deletion Error: {}".format(del_err), file=output_file)

    #    def download_results(self, result_dir):
    #        result_dir = os.path.join(result_dir, 'storage_output')
    #        for bucket in self.output_buckets:
    #            objects = self.connection.list_objects_v2(bucket)
    #            objects = [obj.object_name for obj in objects]
    #            for obj in objects:
    #                self.connection.fget_object(bucket, obj, os.path.join(result_dir, obj))

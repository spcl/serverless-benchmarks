
import docker
import glob
import json
import logging
import os
import subprocess
import shutil
import time
import uuid

from azure.storage.blob import BlobServiceClient

from scripts.experiments_utils import PROJECT_DIR

class blob_storage:
    client = None
    input_containers = []
    input_containers_files = []
    output_containers = []
    replace_existing = False
    
    def __init__(self, conn_string, location, replace_existing):
        self.client = BlobServiceClient.from_connection_string(conn_string)

    def input(self):
        return self.input_containers

    def output(self):
        return self.output_containers

    def create_container(self, name, containers):
        found_container = False
        for c in containers:
            container_name = c['name']
            if name in container_name:
                found_container = True
                # TODO: replace existing bucket if param is passed
                break
        if not found_container:
            random_name = str(uuid.uuid4())[0:16]
            name = '{}-{}'.format(name, random_name)
            self.client.create_container(name)
            logging.info('Created container {}'.format(name))
            return name
        else:
            logging.info('Container {} for {} already exists, skipping.'.format(container_name, name))
            return container_name
    
    def create_buckets(self, benchmark, buckets):
        # Container names do not allow dots
        benchmark = benchmark.replace('.', '-')
        # get existing containers which might fit the benchmark
        containers = self.client.list_containers(
                name_starts_with=benchmark
        )
        for i in range(0, buckets[0]):
            self.input_containers.append(
                self.create_container(
                    '{}-{}-input'.format(benchmark, i),
                    containers
                )
            )
            container = self.input_containers[-1]
            self.input_containers_files.append(
                list(
                    map(
                        lambda x : x['name'],
                        self.client.get_container_client(container).list_blobs()
                    )
                )
            )
        for i in range(0, buckets[1]):
            self.output_containers.append(
                self.create_container(
                    '{}-{}-output'.format(benchmark, i),
                    containers
                )
            )
    
    def uploader_func(self, container_idx, file, filepath):
        container_name = self.input_containers[container_idx]
        if not self.replace_existing:
            for f in self.input_containers_files[container_idx]:
                if f == file:
                    logging.info('Skipping upload of {} to {}'.format(filepath, container_name))
                    return
        client = self.client.get_blob_client(container_name, file)
        with open(file, 'rb') as file_data:
            client.upload_blob(file_data)
        logging.info('Upload {} to {}'.format(filepath, container_name))

class azure:
    config = None
    language = None
    docker_instance = None
    cache_client = None
    logged_in = False

    # secrets
    appId = None
    tenant = None
    password = None

    # resources
    resource_group_name = None
    storage_account_name = None
    storage_connection_string = None
    
    def __init__(self, cache_client, config, language, docker_client):
        self.config = config
        self.language = language
        self.docker_client = docker_client
        self.cache_client = cache_client

        # Read cached credentaisl
        if 'secrets' in config['azure']:
            self.appId = config['azure']['secrets']['appId']
            self.tenant = config['azure']['secrets']['tenant']
            self.password = config['azure']['secrets']['password']
        elif 'AZURE_SECRET_APPLICATION_ID' in os.environ:
            self.appId = os.environ['AZURE_SECRET_APPLICATION_ID']
            self.tenant = os.environ['AZURE_SECRET_TENANT']
            self.password = os.environ['AZURE_SECRET_PASSWORD']
            self.cache_client.update_config(
                val=self.appId,
                keys=['azure', 'secrets', 'appId']
            )
            self.cache_client.update_config(
                val=self.tenant,
                keys=['azure', 'secrets', 'tenant']
            )
            self.cache_client.update_config(
                val=self.password,
                keys=['azure', 'secrets', 'password']
            )
        else:
            # TODO: implement creation of service principal
            raise RuntimeError('Azure credentials are not provided!')

    def shutdown(self):
        if self.docker_instance:
            logging.info('Stopping Azure manage Docker instance')
            self.docker_instance.stop()
            self.logged_in = False
            self.docker_instance = None

    def start(self, code_package=None, restart=False):
        volumes = {}
        if code_package:
            volumes = {
                code_package: {'bind': '/mnt/function/', 'mode': 'rw'}
            }
        if self.docker_instance and restart:
            self.shutdown()
        if not self.docker_instance or restart:
            # Run Azure CLI docker instance in background
            self.docker_instance = self.docker_client.containers.run(
                    image='sebs.manage.azure',
                    command='/bin/bash',
                    user='1000:1000',
                    volumes=volumes,
                    remove=True,
                    stdout=True,
                    stderr=True,
                    detach=True,
                    tty=True
                )
            logging.info('Starting Azure manage Docker instance')

    def execute(self, cmd, no_login=False):
        if not no_login:
            self.login()
        exit_code, out = self.docker_instance.exec_run(cmd)
        if exit_code != 0:
            raise RuntimeError(
                    'Command {} failed at Azure CLI docker!\n Output {}'.format(
                        cmd, out.decode('utf-8')
                    )
                )
        return out

    '''
        Run azure login command on Docker instance.
        Make sure to disable loging for self.execute to avoid infinite recursion.
    '''
    def login(self):
        if not self.logged_in:
            self.start()
            self.execute(
                'az login -u {0} --service-principal --tenant {1} -p {2}'.format(
                    self.appId, self.tenant, self.password
                ),
                no_login=True
            )
            logging.info('Azure login succesful')
            self.logged_in = True

    '''
        Create wrapper object for Azure blob storage.
        First ensure that storage account is created and connection string
        is known. Then, create wrapper and create request number of buckets.
        
        Requires Azure CLI instance in Docker to obtain storage account details.
    '''
    def get_storage(self, benchmark, buckets, replace_existing=False):
        # ensure we have a storage account
        self.storage_account() 
        self.storage = blob_storage(
                self.storage_connection_string,
                self.config['azure']['region'],
                replace_existing
        )
        self.storage.create_buckets(benchmark, buckets)
        return self.storage

    '''
        Locate resource group name in config.
        If not found, then create a new resource group with uuid-based name.

        Requires Azure CLI instance in Docker.
    '''
    def resource_group(self):
        
        # if known, then skip
        if self.resource_group_name:
            return

        # Resource group provided, verify existence
        if 'resource_group' in self.config['azure']:
            self.resource_group_name = self.config['azure']['resource_group']
            ret = self.execute('az group exists --name {0}'.format(
                    self.resource_group_name)
                )
            if ret.decode('utf-8').strip() != 'true':
                raise RuntimeError(
                        'Resource group {} does not exists!'.format(
                            self.resource_group_name
                        )
                    )
        # Create resource group
        else:
            region = self.config['azure']['region']
            uuid_name = str(uuid.uuid1())[0:8]
            # Only underscore and alphanumeric characters are allowed
            self.resource_group_name = 'sebs_resource_group_{}'.format(uuid_name)
            self.execute('az group create --name {0} --location {1}'.format(
                    self.resource_group_name, region
                )
            )
            self.cache_client.update_config(
                val=self.resource_group_name,
                keys=['azure', 'resource_group']
            )
            logging.info('Resource group {} created.'.format(self.resource_group_name))
        logging.info('Azure resource group {} selected'.format(self.resource_group_name))
        return self.resource_group_name

    '''
        Locate storage account connection string in config.
        If not found, then query the string in Azure using current storage account.

        Requires Azure CLI instance in Docker.
    '''
    def query_storage_connection_string(self):
        # if known, then skip
        if self.storage_connection_string:
            return

        if 'connection_string' not in self.config['azure']['storage']:
            # Get storage connection string
            ret = self.execute(
                    'az storage account show-connection-string --name {}'.format(
                        self.storage_account_name)
                )
            ret = json.loads(ret.decode('utf-8'))
            self.storage_connection_string = ret['connectionString']
            self.cache_client.update_config(
                val=self.storage_connection_string,
                keys=['azure', 'storage', 'connection_string']
            )
            logging.info('Storage connection string {}.'.format(self.storage_connection_string))
        else:
            self.storage_connection_string = self.config['azure']['storage']['connection_string']
        return self.storage_connection_string

    '''
        Locate storage account name and connection string in config.
        If not found, then create a new storage account with uuid-based name.

        Requires Azure CLI instance in Docker.
    '''
    def storage_account(self):

        # if known, then skip
        if self.storage_account_name:
            return

        # Storage acount known, only verify correctness
        if 'storage' in self.config['azure']:
            self.storage_account_name = self.config['azure']['storage']['account']
            try:
                # There's no API to check existence.
                # Thus, we attempt to query basic info and check for failures.
                ret = self.execute(
                    'az storage account show --name {0}'.format(
                        self.storage_account_name
                    )
                )
            except RuntimeError as e:
                raise RuntimeError(
                    'Storage account {} existence verification failed!'.format(
                        self.storage_account_name
                    )
                )         
        # Create storage account
        else:
            region = self.config['azure']['region']
            # Ensure we have resource group
            self.resource_group()
            sku = 'Standard_LRS'
            # Create account. Only alphanumeric characters are allowed
            uuid_name = str(uuid.uuid1())[0:8]
            self.storage_account_name = 'sebsstorage{}'.format(uuid_name)
            self.execute(
                ('az storage account create --name {0} --location {1} '
                 '--resource-group {2} --sku {3}').format(
                     self.storage_account_name, region, self.resource_group_name, sku
                    )
            )
            self.cache_client.update_config(
                val=self.storage_account_name,
                keys=['azure', 'storage', 'account']
            )
            logging.info('Storage account {} created.'.format(self.storage_account_name))
        self.query_storage_connection_string()
        logging.info('Azure storage account {} selected'.format(self.storage_account_name))
        return self.storage_account_name

    # TODO: currently we rely on Azure remote build
    # Thus we only rearrange files
    # Directory structure
    # handler
    # - source files
    # - Azure wrappers - handler, storage
    # - additional resources
    # - function.json
    # host.json
    # requirements.txt/package.json
    def package_code(self, dir, benchmark):

        # In previous step we ran a Docker container which installed packages
        # Python packages are in .python_packages because this is expected by Azure
        EXEC_FILES = {
            'python': 'handler.py',
            'nodejs': 'handler.js'
        }
        CONFIG_FILES = {
            'python': ['requirements.txt', '.python_packages'],
            'nodejs': ['package.json', 'node_modules']
        }
        package_config = CONFIG_FILES[self.language]

        handler_dir = os.path.join(dir, 'handler')
        os.makedirs(handler_dir)
        # move all files to 'handler' except package config
        for file in os.listdir(dir):
            if file not in package_config:
                file = os.path.join(dir, file)
                shutil.move(file, handler_dir)
        
        # generate function.json
        # TODO: extension to other triggers than HTTP
        default_function_json = {
          "scriptFile": EXEC_FILES[self.language],
          "bindings": [
            {
              "authLevel": "function",
              "type": "httpTrigger",
              "direction": "in",
              "name": "req",
              "methods": [
                "get",
                "post"
              ]
            },
            {
              "type": "http",
              "direction": "out",
              "name": "$return"
            }
          ]
        }
        json_out = os.path.join(dir, 'handler', 'function.json')
        json.dump(default_function_json, open(json_out, 'w'), indent=2)

        # generate host.json
        default_host_json = {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[1.*, 2.0.0)"
            }
        }
        json.dump(default_host_json, open(os.path.join(dir, 'host.json'), 'w'), indent=2)

        # copy handlers
        wrappers_dir = os.path.join(PROJECT_DIR, 'cloud-frontend', 'azure', self.language)
        for file in glob.glob(os.path.join(wrappers_dir, '*.py')):
            shutil.copy(os.path.join(wrappers_dir, file), handler_dir)

        return dir

    def create_function(self, code_package, benchmark, memory=None, timeout=None):

        self.storage_account()
        self.resource_group()
        # Restart Docker instance to make sure code package is mounted
        self.start(code_package, restart=True)

        region = self.config['azure']['region']
        # only hyphens are allowed
        # and name needs to be globally unique
        uuid_name = str(uuid.uuid1())[0:8]
        func_name = '{}-{}-{}'\
                    .format(benchmark, self.language, uuid_name)\
                    .replace('.', '-')\
                    .replace('_', '-')
        # runtime mapping
        runtimes = {'python': 'python', 'nodejs': 'node'}

        # check if function does not exist
        try:
            self.execute(
                ('az functionapp show --resource-group {} '
                 '--name {}').format(self.resource_group_name, func_name)
            )
        except:
            ret = self.execute(
                ('az functionapp create --resource-group {} '
                 '--os-type Linux --consumption-plan-location {} '
                 '--runtime {} --runtime-version {} --name {} '
                 '--storage-account {}').format(
                    self.resource_group_name, region, runtimes[self.language],
                    self.config['experiments']['runtime'], func_name,
                    self.storage_account_name
                )
            )

        logging.info('Selected {} function app'.format(func_name))
        # publish
        time.sleep(30)
        logging.info('Sleep 30 seconds for Azure to register function app')
        ret = self.execute(
            'bash -c \'cd /mnt/function '
            '&& func azure functionapp publish {} --{} --no-build\''.format(
                func_name, runtimes[self.language]
            )
        )
        url = ""
        for line in ret.split(b'\n'):
            line = line.decode('utf-8')
            if 'Invoke url' in line:
                url = line.split('Invoke url:')[1].strip()
                break

        self.cache_client.add_function(
                deployment='azure',
                benchmark=benchmark,
                language=self.language,
                code_package=code_package,
                config={
                    'azure': {
                        'function': {
                            'invoke_url': url,
                            'runtime': self.config['experiments']['runtime'],
                            'name': func_name,
                            'resource_group': self.resource_group_name,
                        },
                        'storage': {
                            'account': self.storage_account_name,
                            'buckets': {
                                'input': [],
                                'output': []
                            }
                        }
                    }
                }
        )

    def invoke(self, name, payload):
        pass


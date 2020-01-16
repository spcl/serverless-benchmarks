
import docker
import glob
import json
import logging
import os
import subprocess
import shutil
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
    
    def __init__(self, config, language, docker_client):
        self.config = config
        self.language = language
        self.docker_client = docker_client

    def shutdown(self):
        if self.docker_instance:
            self.docker_instance.stop()

    def start(self, code_package):
        if not self.docker_instance:
            # Run Azure CLI docker instance in background
            self.docker_instance = self.docker_client.containers.run(
                    image='sebs.manage.azure',
                    command='/bin/bash',
                    user='1000:1000',
                    volumes={
                        code_package: {'bind': '/mnt/function/', 'mode': 'rw'}
                    },
                    remove=True,
                    stdout=True,
                    stderr=True,
                    detach=True,
                    tty=True
                )
            self.login()

    def execute(self, cmd):
        exit_code, out = self.docker_instance.exec_run(cmd)
        if exit_code != 0:
            raise RuntimeError(
                    'Command {} failed at Azure CLI docker!\n Output {}'.format(
                        cmd, out.decode('utf-8')
                    )
                )
        return out

    def get_storage(self, benchmark, buckets, replace_existing=False):
        self.storage = blob_storage(self.config['secrets']['storage_conn_string'],
                self.config['region'], replace_existing)
        self.storage.create_buckets(benchmark, buckets)
        return self.storage

    def login(self):
        secrets = self.config['secrets']
        appId = secrets.get('appId')
        tenant = secrets.get('tenant')
        password = secrets.get('password')
        # create service principal
        if not appId or not tenant or not password:
            raise RuntimeError('Secrets not provided')
            pass
        self.execute('az login -u {0} --service-principal --tenant {1} -p {2}'.format(appId, tenant, password))
        logging.info('Azure login succesful')

    def resource_group(config):
        resource_group_name = config['resource_group']
        region = config['region']
        # create
        if not resource_group_name:
            uuid_name = uuid.uuid1()[0:8]
            name = 'sebs_resource_group_{)'.format(uuid_name)
            self.execute('az group create --name {0} --location {1}'.format(name, region))
            config['resource_group'] = name
            resource_group_name = name
            logging.info('Resource group {} created.'.format(name))
        # confirm existence
        else:
            ret = self.execute('az group exists --name {0}'.format(resource_group_name))
            if ret.strip() != 'true':
                raise RuntimeError('Resource group {} does not exists!'.format(resource_group_name))
        logging.info('Azure resource group {} selected'.format(resource_group_name))
        return resource_group_name

    def storage_account(config):
        storage_account_name = config['storage_account']
        region = config['region']
        resource_group_name = config['resource_group']
        sku = 'Standard_LRS'
        # create storage account 
        if not storage_account_name:
            uuid_name = uuid.uuid1()[0:8]
            name = 'sebsstorage{)'.format(uuid_name)
            self.execute(
                ('az storage account create --name {0} --location {1}'
                 '--resource-group {2} --sku {3}').format(
                     name, region, resource_group_name, sku
                    )
            )
            config['storage_account'] = name
            storage_account_name = name
            logging.info('Storage account {} created.'.format(name))
            ret = self.execute(
                    'az storage account show-connection-string --name {}'.format(
                        resource_group_name)
                )
            ret = json.loads(ret.decode('utf-8'))
            config['storage_conn_string'] = ret['connectionString']
        # confirm existence
        else:
            try:
                ret = self.execute('az storage account show --name {0}'.format(storage_account_name))
            except RuntimeError as e:
                raise RuntimeError('Storage account {} existence verification failed!'.format(storage_account_name))         
        logging.info('Azure storage account {} selected'.format(storage_account_name))
        return storage_account_name

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

        self.start(code_package)

        storage_account_name = self.config['storage_account']
        region = self.config['region']
        resource_group_name = self.config['resource_group']
        # only hyphens are allowed
        func_name = '{}-{}'\
                    .format(benchmark, self.language)\
                    .replace('.', '-')
        # runtime mapping
        runtimes = {'python': 'python', 'nodejs': 'node'}

        # check if function does not exist
        try:
            self.execute(
                ('az functionapp show --resource-group {} '
                 '--name {}').format(resource_group_name, func_name)
            )
        except:
            ret = self.execute(
                ('az functionapp create --resource-group {} '
                 '--os-type Linux --consumption-plan-location {} '
                 '--runtime {} --runtime-version {} --name {} '
                 '--storage-account {}').format(
                    resource_group_name, region, runtimes[self.language],
                    self.config['runtime'][self.language], func_name,
                    storage_account_name
                )
            )

        # publish
        ret = self.execute(
            'bash -c \'cd /mnt/function && func azure functionapp publish {} --{} --no-build\''.format(func_name, runtimes[self.language])
        )
        url = ""
        for line in ret.split(b'\n'):
            line = line.decode('utf-8')
            print(line)
            if 'Invoke url' in line:
                url = line.split('Invoke url:')[1].strip()
                break
        print(url)

    def invoke(self, name, payload):
        pass


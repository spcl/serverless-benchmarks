#import argparse
#import json
#import logging
#
#from utils import login, resource_group, storage_account
#
#verbose = False
#config = json.load(open('azure_config.json', 'r'))
#azure_config = config['azure']
#logging.basicConfig(
#    level=logging.DEBUG if verbose else logging.INFO
#)
#
## Login to Azure
#login(azure_config['secrets'])
#logging.info('Azure login succesful')
#
## Get or create a resource group
#resource_group_name = resource_group(azure_config)
#logging.info('Azure resource group {} selected'.format(resource_group_name))
#
#storage_account_name = storage_account(azure_config)
#logging.info('Azure storage account {} selected'.format(storage_account_name))
#
#config['azure'] = azure_config
#json.dump(config, open('azure_config.json', 'w'), indent=2)
import glob
import json
import logging
import os
import subprocess
import shutil

class azure:
    config = None
    language = None
    
    def __init__(self, config, language):
        self.config = config
        self.language = language
        self.login()

    def login(self):
        secrets = self.config['secrets']
        appId = secrets.get('appId')
        tenant = secrets.get('tenant')
        password = secrets.get('password')
        # create service principal
        if not appId or not tenant or not password:
            pass
        execute('az login -u {0} --service-principal --tenant {1} -p {2}'.format(appId, tenant, password))
        logging.info('Azure login succesful')

    def resource_group(config):
        resource_group_name = config['resource_group']
        region = config['region']
        # create
        if not resource_group_name:
            uuid_name = uuid.uuid1()[0:8]
            name = 'sebs_resource_group_{)'.format(uuid_name)
            execute('az group create --name {0} --location {1}'.format(name, region))
            config['resource_group'] = name
            resource_group_name = name
            logging.info('Resource group {} created.'.format(name))
        # confirm existence
        else:
            ret = execute('az group exists --name {0}'.format(resource_group_name))
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
            name = 'sebsstorage{)'.format(uuid_name)
            execute(
                ('az storage account create --name {0} --location {1}'
                 '--resource-group {2} --sku {3}').format(
                     name, region, resource_group_name, sku
                    )
            )
            config['storage_account'] = name
            storage_account_name = name
            logging.info('Storage account {} created.'.format(name))
        # confirm existence
        else:
            try:
                ret = execute('az storage account show --name {0}'.format(storage_account_name))
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
    # requirements.txt
    def package_code(dir):

        handler_dir = os.path.join(dir, 'handler')
        os.makedirs(handler_dir)
        shutil.move()
        # move all files to 'handler'
        for root, dirs, files in os.walk(dir):
            for file in files:
                if files != 'requirements.txt':
                    shutil.move(os.path.join(dir, file), handler_dir)
        
        # generate function.json
        # TODO: extension to other triggers than HTTP
        default_function_json = {
          "scriptFile": "handler.py",
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
        json.dump(open(os.path.join(dir, 'handler', 'function.json', 'w'),
            default_function_json, indent=2)

        # generate host.json
        default_host_json = {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[1.*, 2.0.0)"
            }
        }
        json.dump(open(os.path.join(dir, 'host.json'), 'w'), default_host_json, indent=2)

        # copy handlers
        wrappers_dir = os.path.join(PROJECT_DIR, 'cloud-frontend', 'azure', self.language)
        for file in glob.glob(os.path.join(wrappers_dir, '*.py')):
            shutil.copy(os.path.join(wrappers_dir, file), handler_dir)


    def create_function(code_package, benchmark, timeout=None):
        storage_account_name = config['storage_account']
        region = config['region']
        resource_group_name = config['resource_group']
        # valid 
        func_name = '{}-{}'.format(benchmark, self.language).replace('.', '_')
        # runtime mapping
        runtimes = {'python': 'python', 'nodejs': 'node'}

        # check if function does not exist
        try:
            execute(
                ('az functionapp show --resource-group {} '
                 '--name {}').format(resource_group_name, name)
            )
        except:
            ret = execute(
                ('az functionapp create --resource-group {}'
                 '--os-type Linux --consumption-plan-location {}'
                 '--runtime {} --runtime-version {} --name {}'
                 '--storage-account {}').format(
                     resource_group_name, region, runtimes[

            )

        # publish

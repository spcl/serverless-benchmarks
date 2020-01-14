
import logging
import subprocess

def execute(cmd):
    ret = subprocess.run(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if ret.returncode:
        raise RuntimeError('Running {} failed!\n Output: {}'.format(cmd, ret.stdout.decode('utf-8')))
    return ret.stdout.decode('utf-8')

def login(secrets):
    appId = secrets.get('appId')
    tenant = secrets.get('tenant')
    password = secrets.get('password')
    # create service principal
    if not appId or not tenant or not password:
        pass
    execute('az login -u {0} --service-principal --tenant {1} -p {2}'.format(appId, tenant, password))

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
            
    return storage_account_name

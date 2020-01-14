import argparse
import json
import logging

from utils import login, resource_group, storage_account

verbose = False
config = json.load(open('azure_config.json', 'r'))
azure_config = config['azure']
logging.basicConfig(
    level=logging.DEBUG if verbose else logging.INFO
)

# Login to Azure
login(azure_config['secrets'])
logging.info('Azure login succesful')

# Get or create a resource group
resource_group_name = resource_group(azure_config)
logging.info('Azure resource group {} selected'.format(resource_group_name))

storage_account_name = storage_account(azure_config)
logging.info('Azure storage account {} selected'.format(storage_account_name))

config['azure'] = azure_config
json.dump(config, open('azure_config.json', 'w'), indent=2)

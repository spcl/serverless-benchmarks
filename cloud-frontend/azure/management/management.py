import argparse
import json

from login import login


azure_config = json.load(open('azure_config.json', 'r'))

# Login to Azure
azure_config['secrets'] = login(azure_config['secrets'])

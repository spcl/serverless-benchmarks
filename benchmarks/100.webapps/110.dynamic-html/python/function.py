from datetime import datetime                                                   
from random import sample  
from os import path
from time import time_ns
from jsonschema import validate

import os

from jinja2 import Template

SCRIPT_DIR = path.abspath(path.join(path.dirname(__file__)))

def handler(event):

    schema = {
        "type": "object",
        "required": ["username", "random_len"],
        "properties": {
            "username": {"type": "string"},
            "random_len": {"type": "integer"}
        }
    }
    try:
        validate(event, schema=schema)
    except:
        return { 'status': 'failure', 'result': 'Some value(s) is/are not found in JSON data or of incorrect type' }
    # start timing
    name = event['username']
    size = event['random_len']
    
    cur_time = datetime.now()
    random_numbers = sample(range(0, 1000000), size)
    template = Template(open(path.join(SCRIPT_DIR, 'templates', 'template.html'), 'r').read())
    html = template.render(username = name, cur_time = cur_time, random_numbers = random_numbers)
    # end timing
    # dump stats 
    return { 'status': 'success', 'result': 'Returned with no error', 'measurement': html }

#!/usr/bin/env python3

import docker
import json
import os
import subprocess
import sys

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(dir_path, os.path.pardir))
from sebs.config import SeBSConfig

docker_client = docker.from_env()
config = SeBSConfig()
azure_docker_image = '{}:manage.azure'.format(config.docker_repository())
container = docker_client.containers.run(
    image=azure_docker_image,
    command="/bin/bash",
    user="1000:1000",
    remove=True,
    stdout=True,
    stderr=True,
    detach=True,
    tty=True
)
print('Please provide the intended principal name')
principal_name = input()
_, out = container.exec_run("az login", stream=True)
print('Please follow the login instructions to generate credentials...')
print(next(out).decode())
# wait for login finish
ret = next(out)
ret_json = json.loads(ret.decode())
print('Loggin succesfull with user {}'.format(ret_json[0]['user']))
status, out = container.exec_run("az ad sp create-for-rbac --name {} --only-show-errors".format(principal_name))
if status:
    print('Unsuccesfull principal creation!')
    print(out.decode())
else:
    credentials = json.loads(out.decode())
    print('Created service principal {}'.format(credentials['name']))
    print('AZURE_SECRET_APPLICATION_ID = {}'.format(credentials['appId']))
    print('AZURE_SECRET_APPLICATION_TENANT = {}'.format(credentials['tenant']))
    print('AZURE_SECRET_APPLICATION_PASSWORD = {}'.format(credentials['password']))

container.stop()


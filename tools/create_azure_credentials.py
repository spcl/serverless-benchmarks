#!/usr/bin/env python3

import argparse
import docker
import json
import os
import subprocess
import sys

parser = argparse.ArgumentParser(description="Create Azure credentials.")
parser.add_argument("--subscription", default=None, type=str, action="store")
args = parser.parse_args()

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(dir_path, os.path.pardir))
from sebs.config import SeBSConfig

docker_client = docker.from_env()
config = SeBSConfig()
repo_name = config.docker_repository()
image_name = "manage.azure"
try:
    docker_client.images.get(repo_name + ":" + image_name)
except docker.errors.ImageNotFound:
    try:
        print(
            "Docker pull of image {repo}:{image}".format(
                repo=repo_name, image=image_name
            )
        )
        docker_client.images.pull(repo_name, image_name)
    except docker.errors.APIError:
        raise RuntimeError(
            "Docker pull of image {} failed!".format(image_name)
        )
container = docker_client.containers.run(
    image=repo_name + ":" + image_name,
    command="/bin/bash",
    environment={
        "CONTAINER_UID": str(os.getuid()),
        "CONTAINER_GID": str(os.getgid()),
        "CONTAINER_USER": "docker_user"
    },
    remove=True,
    stdout=True,
    stderr=True,
    detach=True,
    tty=True
)
print('Please provide the intended principal name')
principal_name = input()
_, out = container.exec_run("az login", user="docker_user", stream=True)
print('Please follow the login instructions to generate credentials...')
print(next(out).decode())
# wait for login finish
ret = next(out)
ret_json = json.loads(ret.decode())
print('Logging succesfull with user {}'.format(ret_json[0]['user']))

cmd = "az ad sp create-for-rbac --name {} --only-show-errors".format(principal_name)
if args.subscription:
    cmd = f"{cmd} --role Contributor --scopes /subscriptions/{args.subscription}"

status, out = container.exec_run(cmd,user="docker_user")
if status:
    print('Unsuccesfull principal creation!')
    print(out.decode())
else:
    credentials = json.loads(out.decode())
    print('Created service principal {}'.format(credentials['displayName']))
    print('AZURE_SECRET_APPLICATION_ID = {}'.format(credentials['appId']))
    print('AZURE_SECRET_TENANT = {}'.format(credentials['tenant']))
    print('AZURE_SECRET_PASSWORD = {}'.format(credentials['password']))

container.stop()


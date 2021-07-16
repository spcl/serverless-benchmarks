#!/usr/bin/env python3

import argparse
import docker
import json
import os
import shutil

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
DOCKER_DIR = os.path.join(PROJECT_DIR, 'docker')

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('--deployment', default=None, choices=['local', 'aws', 'azure', 'gcp'], action='store')
parser.add_argument('--type', default=None, choices=['build', 'run', 'manage'], action='store')
parser.add_argument('--language', default=None, choices=['python', 'nodejs'], action='store')
args = parser.parse_args()
config = json.load(open(os.path.join(PROJECT_DIR, 'config', 'systems.json'), 'r'))
client = docker.from_env()

def build(image_type, system, username, language=None,version=None, version_name=None):

    msg = 'Build *{}* Dockerfile for *{}* system'.format(image_type, system)
    if language:
        msg += ' with language *' + language + '*'
    if version:
        msg += ' with version *' + version + '*'
    print(msg)
    dockerfile = os.path.join(PROJECT_DIR, 'docker', 'Dockerfile.{}.{}'.format(image_type, system))
    target = f'{config["general"]["docker_repository"]}:{image_type}.{system}'
    if language:
        dockerfile += '.' + language
        target += '.' + language
    if version:
        target += '.' + version

    buildargs={
        'USER': username,
        'VERSION': version
    }
    if version:
        buildargs['BASE_IMAGE'] = version_name
    print('Build img {} in {} from file {} with args {}'.format(target, PROJECT_DIR, dockerfile, buildargs))
    client.images.build(
        path=PROJECT_DIR,
        dockerfile=dockerfile,
        buildargs=buildargs,
        tag=target
    )

def build_language(system, language, language_config):
    username = language_config['username']
    configs = []
    if 'base_images' in language_config:
        for version, base_image in language_config['base_images'].items():
            configs.append([version, base_image])
    else:
        configs.append([None, None])

    for image in configs:
        if args.type is None:
            for image_type in language_config['images']:
                build(image_type, system, username, language, *image)
        else:
            build(args.type, system, username, language, *image)

def build_systems(system, system_config):

    if args.type == 'manage':
        if 'images' in system_config:
            build(args.type, system, system_config['images']['manage']['username'])
        else:
            print(f'Skipping manage image for {system}')
    else:
        if args.language:
            build_language(system, args.language, system_config['languages'][args.language])
        else:
            for language, language_dict in system_config['languages'].items():
                build_language(system, language, language_dict)

if args.deployment is None:
    for system, system_dict in config.items():
        if system == 'general':
            continue
        build_systems(system, system_dict)
else:
    build_systems(args.deployment, config[args.deployment])
                


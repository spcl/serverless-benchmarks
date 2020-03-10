#!/usr/bin/env python3

import argparse
import docker
import json
import os
import shutil

DOCKER_DIR = os.path.join('cloud_frontend', 'docker')
PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('--system', default=None, choices=['local', 'aws', 'azure'], action='store')
parser.add_argument('--run', default=None, choices=['build', 'run', 'manage'], action='store')
parser.add_argument('--language', default=None, choices=['python', 'nodejs'], action='store')
args = parser.parse_args()
config = json.load(open(os.path.join('config', 'systems.json'), 'r'))
client = docker.from_env()

def prepare_build_ctx(path, dockerfile, run, language):
    shutil.copyfile(os.path.join(DOCKER_DIR, dockerfile), os.path.join(path, dockerfile))
    # copy pypapi
    if run == 'run' and language == 'python':
        papi_dest = os.path.join(path, 'pypapi')
        if os.path.exists(papi_dest):
            shutil.rmtree(papi_dest)
        shutil.copytree(os.path.join(PROJECT_DIR, 'third-party', 'pypapi'), papi_dest)

def clean_build_ctx(path, dockerfile, run, language):
    os.remove(os.path.join(path, dockerfile))
    # copy pypapi
    if run == 'run' and language == 'python':
        shutil.rmtree(os.path.join(path, 'pypapi'))

def build(run, system, username, language=None,version=None, version_name=None):

    msg = 'Build *{}* Dockerfile for *{}* system'.format(run, system)
    if language:
        msg += ' with language *' + language + '*'
    if version:
        msg += ' with version *' + version + '*'
    print(msg)
    path = os.path.join(PROJECT_DIR, 'cloud_frontend', system)
    dockerfile = 'Dockerfile.{}.{}'.format(run, system)
    target = 'sebs.{}.{}'.format(run, system)
    if language:
        dockerfile += '.' + language
        target += '.' + language
    if version:
        target += '.' + version
    prepare_build_ctx(path, dockerfile, run, language)

    buildargs={
        'USER': username,
        'VERSION': version
    }
    if version:
        buildargs['BASE_IMAGE'] = version_name
    client.images.build(
        path=path,
        dockerfile=dockerfile,
        buildargs=buildargs,
        tag=target
    )
    clean_build_ctx(path, dockerfile, run, language)

def build_language(system, language, language_config):
    username = language_config['username']
    configs = []
    if 'base_images' in language_config:
        for version, base_image in language_config['base_images'].items():
            configs.append([version, base_image])
    else:
        configs.append([None, None])

    for image in configs:
        if args.run is None:
            for run in language_config['images']:
                build(run, system, username, language, *image)
        else:
            build(args.run, system, username, language, *image)

def build_systems(system, system_config):

    if args.run == 'manage':
        build(args.run, system, system_config['images']['manage']['username'])
    else:
        if args.language:
            build_language(system, args.language, system_config['languages'][args.language])
        else:
            for language, language_dict in system_config['languages'].items():
                build_language(system, language, language_dict)

if args.system is None:
    for system, system_dict in config.items():
        build_systems(system, system_dict)
else:
    build_systems(args.system, config[args.system])
                


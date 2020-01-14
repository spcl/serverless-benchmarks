
import argparse
import docker
import json
import os
import shutil

DOCKER_DIR = os.path.join('cloud-frontend', 'docker')
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('--system', default=None, choices=['local', 'aws'], action='store')
parser.add_argument('--run', default=None, choices=['build', 'run'], action='store')
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
        shutil.copytree(os.path.join(SCRIPT_DIR, 'third-party', 'pypapi'), papi_dest)

def clean_build_ctx(path, dockerfile, run, language):
    os.remove(os.path.join(path, dockerfile))
    # copy pypapi
    if run == 'run' and language == 'python':
        shutil.rmtree(os.path.join(path, 'pypapi'))

def build(run, system, language, username, version, version_name):
    print('Build {} Dockerfile for {} system, language {} with version {}'.format(run, system, language, version))
    path = os.path.join(SCRIPT_DIR, 'cloud-frontend', system)
    dockerfile = 'Dockerfile.{}.{}.{}'.format(run, system, language)
    target = 'sebs.{}.{}.{}'.format(run, system, language)
    if version is not None:
        target += '.' + version
    prepare_build_ctx(path, dockerfile, run, language)

    buildargs={
        'USER': username
    }
    if version is not None:
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
                build(run, system, language, username, *image)
        else:
            build(args.run, system, language, version, *image)

def build_systems(system, system_config):
    if args.language is None:
        for language, language_dict in system_config['images'].items():
            build_language(system, language, language_dict)
    else:
        build_language(system, args.language, system_config[args.language])

if args.system is None:
    for system, system_dict in config.items():
        build_systems(system, system_dict)
else:
    build_systems(args.system, config[args.system])
                


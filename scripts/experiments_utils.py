import docker
import glob
import logging
import json
import os
import subprocess
import shutil

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
PACK_CODE_APP = 'pack_code_{}.sh'

# Executing with shell provides options such as wildcard expansion
def execute(cmd, shell=False):
    if not shell:
        cmd = cmd.split()
    ret = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if ret.returncode:
        raise RuntimeError('Running {} failed!\n Output: {}'.format(cmd, ret.stdout.decode('utf-8')))
    return ret.stdout.decode('utf-8')

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None

def create_output(dir, verbose):
    output_dir = os.path.abspath(dir)
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    os.chdir(output_dir)
    logging.basicConfig(
        filename=os.path.join(output_dir, 'out.log'),
        filemode='w',
        format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
        level=logging.DEBUG if verbose else logging.INFO
    )
    return output_dir

'''
    Locate directory corresponding to a benchmark in benchmarks
    or benchmarks-data directory.

    :param benchmark: Benchmark name.
    :param path: Path for lookup, relative to repository.
    :return: relative path to directory corresponding to benchmark
'''
def find_benchmark(benchmark: str, path: str):
    benchmarks_dir = os.path.join(PROJECT_DIR, path)
    benchmark_path = find(benchmark, benchmarks_dir)
    if benchmark_path is None:
        logging.error('Could not find benchmark {} in {}'.format(args.benchmark, benchmarks_dir))
        sys.exit(1)
    return benchmark_path

def create_code_package(docker, client, config, benchmark, benchmark_path):

    run = config['deployment']
    language = config['language']
    runtime = config['runtime']
    code_package = benchmark + '.zip'

    # is the benchmark supported for this language?
    config = json.load(open(os.path.join(benchmark_path, 'config.json')))
    if language not in config['languages']:
        raise RuntimeError('Benchmark {} not available for language {}'.format(benchmark, language))
    benchmark_path = os.path.join(benchmark_path, language)

    # create directory to be deployed
    if os.path.exists('code'):
        shutil.rmtree('code')
    os.makedirs('code')

    # copy function code
    FILES = {
        'python': ['*.py', 'requirements.txt'],
        'nodejs': ['*.js', 'package.json']
    }
    for file_type in FILES[language]:
        for file in glob.glob(os.path.join(benchmark_path, file_type)):
            shutil.copy2( os.path.join(benchmark_path, file), 'code')

    # Add additional resources and binaries, if required
    if os.path.exists(os.path.join(benchmark_path, 'init.sh')):
        out = subprocess.run('/bin/bash {0}/init.sh $(pwd)/code false'.format(benchmark_path),
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        logging.debug(out.stdout.decode('utf-8'))

    # Add deployment files
    system_config = json.load(open(os.path.join(PROJECT_DIR, 'config', 'systems.json')))[run]['languages'][language]
    if 'deployment' in system_config:
        handlers_dir = os.path.join(PROJECT_DIR, 'cloud_frontend', run, language)
        handlers = [os.path.join(handlers_dir, file) for file in system_config['deployment']['files']]
        for file in handlers:
            shutil.copy2(file, 'code')

    # Add deployment packages
    if language == 'python':
        # append to the end of file
        packages = system_config['deployment']['packages']
        if len(packages):
            with open(os.path.join('code', 'requirements.txt'), 'a') as out:
                for package in packages:
                    out.write(package)
    # modify package.json
    elif language == 'nodejs':
        packages = system_config['deployment']['packages']
        if len(packages):
            package_config = os.path.join('code', 'package.json')
            package_json = json.load(open(package_config, 'r'))
            for key, val in packages.items():
                package_json['dependencies'][key] = val
            json.dump(package_json, open(package_config, 'w'), indent=2)
    else:
        raise RuntimeError()

    # do we have docker image for this run and language?
    if 'build' not in system_config['images']:
        logging.info('Docker build image for {} run with {} is not available, skipping'.format(run, language))
    else:
        container_name = 'sebs.build.{}.{}.{}'.format(run, language, runtime)
        try:
            img = docker.images.get(container_name)
        except docker.errors.ImageNotFound as err:
            raise RuntimeError('Docker build image {} not found!'.format(img))

        # run Docker container to install packages
        PACKAGE_FILES = {
            'python': 'requirements.txt',
            'nodejs': 'package.json'
        }
        file = os.path.join('code', PACKAGE_FILES[language])
        if os.path.exists(file):
            docker.containers.run(
                container_name,
                volumes={
                    os.path.abspath('code') : {'bind': '/mnt/function', 'mode': 'rw'}
                },
                environment={
                    'APP': benchmark
                },
                user='1000:1000',
                remove=True,
                stdout=True, stderr=True,
            )

    logging.info('Created {}/code package for run on {} with {}:{}'.format(os.getcwd(), run, language, runtime))

    # measure uncompressed code size
    # https://stackoverflow.com/questions/1392413/calculating-a-directorys-size-using-python
    from pathlib import Path
    root_directory = Path('code')
    code_size = sum(f.stat().st_size for f in root_directory.glob('**/*') if f.is_file() )

    # now let's do the last step - add config files and create deployment
    # package if necessary
    package_code = os.path.join(os.path.abspath('code'))
    package_code = client.package_code(package_code, benchmark)

    return package_code, code_size, config

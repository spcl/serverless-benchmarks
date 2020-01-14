import docker
import logging
import json
import os
import subprocess
import shutil

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
PACK_CODE_APP = 'pack_code_{}.sh'

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
        filename='out.log',
        filemode='w',
        format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
        level=logging.DEBUG if verbose else logging.INFO
    )
    return output_dir

def find_benchmark(benchmark):
    benchmarks_dir = os.path.join(SCRIPT_DIR, '..', 'benchmarks')
    benchmark_path = find(benchmark, benchmarks_dir)
    if benchmark_path is None:
        logging.error('Could not find benchmark {} in {}'.format(args.benchmark, benchmarks_dir))
        sys.exit(1)
    return benchmark_path

#def create_code_package(run, benchmark, benchmark_path, language, verbose):
#    config = json.load(open(os.path.join(benchmark_path, 'config.json')))
#    if language not in config['languages']:
#        raise RuntimeError('Benchmark {} not available for language {}'.format(benchmark, language))
#    output = subprocess.run('{} -b {} -l {} {}'.format(
#            os.path.join(SCRIPT_DIR, PACK_CODE_APP.format(run)),
#            benchmark_path, language,
#            '-v' if verbose else ''
#        ).split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
#    logging.debug(output.stdout.decode('utf-8'))
#    code_package = '{}.zip'.format(benchmark)
#    # measure uncompressed code size with unzip -l
#    ret = subprocess.run(['unzip -l {} | awk \'END{{print $1}}\''.format(code_package)], shell=True, stdout = subprocess.PIPE)
#    if ret.returncode != 0:
#        raise RuntimeError('Code size measurement failed: {}'.format(ret.stdout.decode('utf-8')))
#    code_size = int(ret.stdout.decode('utf-8'))
#    return code_package, code_size, config

def create_code_package(docker, config, benchmark, benchmark_path):

    run = config['deployment']
    language = config['language']
    runtime = config['runtime']
    code_package = benchmark + '.zip'

    # is the benchmark supported for this language?
    config = json.load(open(os.path.join(benchmark_path, 'config.json')))
    if language not in config['languages']:
        raise RuntimeError('Benchmark {} not available for language {}'.format(benchmark, language))

    benchmark_path = os.path.join(benchmark_path, language)

    # do we have docker image for this run and language?
    system_config = json.load(open(os.path.join(PROJECT_DIR, 'config', 'systems.json')))[run][language]
    if 'build' not in system_config['images']:
        raise RuntimeError('Docker build image for {} run with {} is not available!'.format(run, language))
    container_name = 'sebs.build.{}.{}.{}'.format(run, language, runtime)
    try:
        img = docker.images.get(container_name)
    except docker.errors.ImageNotFound as err:
        raise RuntimeError('Docker build image {} not found!'.format(img))

    # pack function code
    FILES = {
        'python': '{1}/*.py {1}/requirements.txt',
        'nodejs': '{1}/*.js {1}/package.json'
    }
    cmd = ('zip -rj {0} ' + FILES[language]).format(code_package, benchmark_path)
    out = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logging.debug(out.stdout.decode('utf-8'))

    # run Docker container to install packages
    PACKAGE_FILES = {
        'python': 'requirements.txt',
        'nodejs': 'package.json'
    }
    file = os.path.join(benchmark_path, PACKAGE_FILES[language])
    if os.path.exists(file):
        shutil.copy(file, os.getcwd())
        docker.containers.run(
            container_name,
            volumes={
                os.getcwd(): {'bind': '/mnt/function', 'mode': 'rw'}
            },
            environment={
                'APP': benchmark
            },
            user='1000:1000',
            remove=True,
            stdout=True, stderr=True,
        )

    # Add additional binaries, if required
    if os.path.exists(os.path.join(benchmark_path, 'init.sh')):
        out = subprocess.run('/bin/bash {0}/init.sh $(pwd)/{1} false'.format(benchmark_path, code_package),
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        logging.debug(out.stdout.decode('utf-8'))

    # Add deployment files
    if 'deployment' in system_config:
        handlers_dir = os.path.join(PROJECT_DIR, 'cloud-frontend', run, language)
        handlers = [os.path.join(handlers_dir, file) for file in system_config['deployment']['files']]
        out = subprocess.run(
                'zip -quj {0} {1}'.format(code_package, ' '.join(handlers)).split(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        logging.debug(out.stdout.decode('utf-8'))

    logging.info('Created {} code package for run on {} with {}:{}'.format(code_package, run, language, runtime))

    # measure uncompressed code size with unzip -l
    ret = subprocess.run(
            'unzip -l {} | awk \'END{{print $1}}\''.format(code_package),
            shell=True,
            stdout = subprocess.PIPE
        )
    if ret.returncode != 0:
        raise RuntimeError('Code size measurement failed: {}'.format(ret.stdout.decode('utf-8')))
    code_size = int(ret.stdout.decode('utf-8'))
    return code_package, code_size, config

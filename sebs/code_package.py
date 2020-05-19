
import docker
import glob
import hashlib
import json
import logging
import os
import shutil
import subprocess

from .cache import Cache
from .utils import project_absolute_path, find_benchmark

'''
    Creates code package representing a benchmark with all code and assets
    prepared and dependency install performed within Docker image corresponding
    to the cloud deployment.

    The behavior of the class depends on cache state:
    1)  First, if there's no cache entry, a code package is built.
    2)  Otherwise, the hash of the entire benchmark is computed and compared
        with the cached value. If changed, then rebuilt then benchmark.
    3)  Otherwise, just return the path to cache code.
'''
class CodePackage:

    @property
    def benchmark(self):
        return self._benchmark
    
    @property
    def benchmark_path(self):
        return self._benchmark_path

    @property
    def benchmark_config(self):
        return self._benchmark_config

    @property
    def code_location(self):
        return self._code_location

    @property
    def cached_config(self):
        return self._cached_config

    @property
    def is_cached(self):
        return self._is_cached

    @property
    def is_cached_valid(self):
        return self._is_cached_valid

    @property
    def code_size(self):
        return self._code_size

    @property
    def hash(self):
        if not self._hash_value:
            path = os.path.join(self.benchmark_path, self._language)
            self._hash_value = CodePackage.hash_directory(path, self._language)
        return self._hash_value

    def __init__(self, benchmark: str, config: dict, output_dir: str,
            system_config: dict, cache_client: Cache,
            docker_client: docker.client,
            forced_update: bool=False):
        self._benchmark = benchmark
        self._deployment = config['experiments']['deployment']['name']
        self._language = config['experiments']['language']
        self._runtime = config['experiments']['runtime']
        self._benchmark_path = find_benchmark(self.benchmark, 'benchmarks')
        if not self._benchmark_path:
            raise RuntimeError('Benchmark {benchmark} not found!'.format(benchmark=self._benchmark))
        with open( os.path.join(self.benchmark_path, 'config.json') ) as json_file:
            self._benchmark_config = json.load(json_file)
        if self._language not in self._benchmark_config['languages']:
            raise RuntimeError(
                    'Benchmark {} not available for language {}'.format(
                        self.benchmark, self._language
                    )
                )
        self._system_config = system_config['languages'][self._language]
        self._cache_client = cache_client
        self._docker_client = docker_client
        self._hash_value = None

        # verify existence of function in cache
        self.query_cache()
        if forced_update:
            self._is_cached_valid = False
        if not self.is_cached or not self.is_cached_valid:
            self._code_location = self.build(output_dir)

    '''
        Compute MD5 hash of an entire directory.
    '''
    @staticmethod
    def hash_directory(directory: str, language: str):

        hash_sum = hashlib.md5()
        FILES = {
            'python': ['*.py', 'requirements.txt*'],
            'nodejs': ['*.js', 'package.json']
        }
        NON_LANG_FILES = ['*.sh', '*.json']
        selected_files = FILES[language] + NON_LANG_FILES
        for file_type in selected_files:
            for f in glob.glob( os.path.join(directory, file_type) ):
                path = os.path.join(directory, f)
                with open(path, 'rb') as opened_file:
                    hash_sum.update( opened_file.read() )
        return hash_sum.hexdigest()


    def query_cache(self):
        self._cached_config, self._code_location = self._cache_client.get_function(
                    deployment=self._deployment,
                    benchmark=self._benchmark,
                    language=self._language
        )
        if self.cached_config is not None:
            # compare hashes
            current_hash = self.hash
            old_hash = self.cached_config['hash']
            self._code_size = self.cached_config['code_size']
            self._is_cached = True
            self._is_cached_valid = current_hash == old_hash
        else:
            self._is_cached = False

    def copy_code(self, output_dir):
        FILES = {
            'python': ['*.py', 'requirements.txt*'],
            'nodejs': ['*.js', 'package.json']
        }
        path = os.path.join(self.benchmark_path, self._language)
        for file_type in FILES[self._language]:
            for f in glob.glob( os.path.join(path, file_type) ):
                shutil.copy2( os.path.join(path, f), output_dir)

    def add_benchmark_data(self, output_dir):
        cmd = '/bin/bash {benchmark_path}/init.sh {output_dir} false'
        paths = [
            self.benchmark_path,
            os.path.join(self.benchmark_path, self._language)
        ]
        for path in paths:
            if os.path.exists( os.path.join(path, 'init.sh') ):
                out = subprocess.run(
                        cmd.format(
                            benchmark_path=path,
                            output_dir=output_dir
                        ),
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT
                    )
                logging.debug(out.stdout.decode('utf-8'))

    def add_deployment_files(self, output_dir):
        if 'deployment' in self._system_config:
            handlers_dir = project_absolute_path(
                'benchmarks', 'wrappers', self._deployment, self._language
            )
            handlers = [
                os.path.join(handlers_dir, file)
                for file in self._system_config['deployment']['files']
            ]
            for file in handlers:
                shutil.copy2(file, 'code')

    def add_deployment_package_python(self, output_dir):
        # append to the end of requirements file
        packages = self._system_config['deployment']['packages']
        if len(packages):
            with open(os.path.join(output_dir, 'requirements.txt'), 'a') as out:
                for package in packages:
                    out.write(package)

    def add_deployment_package_nodejs(self, output_dir):
        # modify package.json
        packages = self._system_config['deployment']['packages']
        if len(packages):
            package_config = os.path.join(output_dir, 'package.json')
            package_json = json.load(open(package_config, 'r'))
            for key, val in packages.items():
                package_json['dependencies'][key] = val
            json.dump(package_json, open(package_config, 'w'), indent=2)

    def add_deployment_package(self, output_dir):
        if self._language == 'python':
            self.add_deployment_package_python(output_dir)
        elif self._language == 'nodejs':
            self.add_deployment_package_nodejs(output_dir)
        else:
            raise NotImplementedError

    @staticmethod
    def directory_size(directory: str):
        from pathlib import Path
        root = Path(directory)
        sizes = [f.stat().st_size for f in root.glob('**/*') if f.is_file()]
        return sum(sizes)

    def install_dependencies(self, output_dir):
        # do we have docker image for this run and language?
        if 'build' not in self._system_config['images']:
            logging.info(
                ('Docker build image for {deployment} run in {language} '
                'is not available, skipping').format(
                    deployment=self._deployment,
                    language=self._language)
            )
        else:
            container_name = 'sebs.build.{deployment}.{language}.{runtime}'.format(
                    deployment=self._deployment,
                    language=self._language,
                    runtime=self._runtime
            )
            try:
                img = self._docker_client.images.get(container_name)
            except docker.errors.ImageNotFound as err:
                raise RuntimeError('Docker build image {} not found!'.format(container_name))

            # does this benchmark has package.sh script?
            volumes = {}
            package_script = os.path.abspath(os.path.join(
                        self._benchmark_path, self._language, 'package.sh'
            ))
            if os.path.exists(package_script):
                volumes[package_script] = {'bind': '/mnt/function/package.sh', 'mode': 'ro'}

            # run Docker container to install packages
            PACKAGE_FILES = {
                'python': 'requirements.txt',
                'nodejs': 'package.json'
            }
            file = os.path.join('code', PACKAGE_FILES[self._language])
            if os.path.exists(file):
                try:
                    stdout = self._docker_client.containers.run(
                        container_name,
                        volumes={
                            **volumes,
                            os.path.abspath('code') : {
                                'bind': '/mnt/function',
                                'mode': 'rw'
                            }
                        },
                        environment={
                            'APP': self.benchmark
                        },
                        user='1000:1000',
                        remove=True,
                        stdout=True, stderr=True
                    )
                    # Pass to output information on optimizing builds.
                    # Useful for AWS where packages have to obey size limits.
                    for line in stdout.decode('utf-8').split('\n'):
                        if 'size' in line:
                            logging.info('Docker build: {}'.format(line))
                except docker.errors.ContainerError as e:
                    logging.error('Package build failed!')
                    logging.error(e)
                    raise e

    def recalculate_code_size(self):
        self._code_size = CodePackage.directory_size(self._output_dir)
        return self._code_size

    def build(self, output_dir):

        self._output_dir = os.path.join(output_dir, 'code')
        # create directory to be deployed
        if os.path.exists(self._output_dir):
            shutil.rmtree(self._output_dir)
        os.makedirs(self._output_dir)

        self.copy_code(self._output_dir)
        self.add_benchmark_data(self._output_dir)
        self.add_deployment_files(self._output_dir)
        self.add_deployment_package(self._output_dir)
        self.install_dependencies(self._output_dir)

        self._code_size = CodePackage.directory_size(self._output_dir)
        logging.info('Created code package for run on {deployment} with {language}:{runtime}'.format(
            deployment=self._deployment,
            language=self._language,
            runtime=self._runtime
            )
        )
        return os.path.abspath(self._output_dir)


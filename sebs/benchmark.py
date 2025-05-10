import glob
import hashlib
import json
import os
import shutil
import subprocess
from abc import abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

import docker

from sebs.config import SeBSConfig
from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.resources import SystemResources
from sebs.utils import find_benchmark, project_absolute_path, LoggingBase
from sebs.types import BenchmarkModule
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebs.experiments.config import Config as ExperimentConfig
    from sebs.faas.function import Language


class BenchmarkConfig:
    def __init__(
        self, timeout: int, memory: int, languages: List["Language"], modules: List[BenchmarkModule]
    ):
        self._timeout = timeout
        self._memory = memory
        self._languages = languages
        self._modules = modules

    @property
    def timeout(self) -> int:
        return self._timeout

    @timeout.setter
    def timeout(self, val: int):
        self._timeout = val

    @property
    def memory(self) -> int:
        return self._memory

    @memory.setter
    def memory(self, val: int):
        self._memory = val

    @property
    def languages(self) -> List["Language"]:
        return self._languages

    @property
    def modules(self) -> List[BenchmarkModule]:
        return self._modules

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(json_object: dict) -> "BenchmarkConfig":
        from sebs.faas.function import Language

        return BenchmarkConfig(
            json_object["timeout"],
            json_object["memory"],
            [Language.deserialize(x) for x in json_object["languages"]],
            [BenchmarkModule(x) for x in json_object["modules"]],
        )


"""
    Creates code package representing a benchmark with all code and assets
    prepared and dependency install performed within Docker image corresponding
    to the cloud deployment.

    The behavior of the class depends on cache state:
    1)  First, if there's no cache entry, a code package is built.
    2)  Otherwise, the hash of the entire benchmark is computed and compared
        with the cached value. If changed, then rebuilt then benchmark.
    3)  Otherwise, just return the path to cache code.
"""


class Benchmark(LoggingBase):
    @staticmethod
    def typename() -> str:
        return "Benchmark"

    @property
    def benchmark(self):
        return self._benchmark

    @property
    def benchmark_path(self):
        return self._benchmark_path

    @property
    def benchmark_config(self) -> BenchmarkConfig:
        return self._benchmark_config

    @property
    def code_package(self) -> dict:
        return self._code_package

    @property
    def functions(self) -> Dict[str, Any]:
        return self._functions

    @property
    def code_location(self):
        if self.code_package:
            return os.path.join(self._cache_client.cache_dir, self.code_package["location"])
        else:
            return self._code_location

    @property
    def is_cached(self):
        return self._is_cached

    @is_cached.setter
    def is_cached(self, val: bool):
        self._is_cached = val

    @property
    def is_cached_valid(self):
        return self._is_cached_valid

    @is_cached_valid.setter
    def is_cached_valid(self, val: bool):
        self._is_cached_valid = val

    @property
    def code_size(self):
        return self._code_size

    @property
    def container_uri(self) -> str:
        assert self._container_uri is not None
        return self._container_uri

    @property
    def language(self) -> "Language":
        return self._language

    @property
    def language_name(self) -> str:
        return self._language.value

    @property
    def language_version(self):
        return self._language_version

    @property
    def has_input_processed(self) -> bool:
        return self._input_processed

    @property
    def uses_storage(self) -> bool:
        return self._uses_storage

    @property
    def uses_nosql(self) -> bool:
        return self._uses_nosql

    @property
    def architecture(self) -> str:
        return self._architecture

    @property
    def container_deployment(self):
        return self._container_deployment

    @property  # noqa: A003
    def hash(self):
        path = os.path.join(self.benchmark_path, self.language_name)
        self._hash_value = Benchmark.hash_directory(path, self._deployment_name, self.language_name)
        return self._hash_value

    @hash.setter  # noqa: A003
    def hash(self, val: str):
        """
        Used only for testing purposes.
        """
        self._hash_value = val

    def __init__(
        self,
        benchmark: str,
        deployment_name: str,
        config: "ExperimentConfig",
        system_config: SeBSConfig,
        output_dir: str,
        cache_client: Cache,
        docker_client: docker.client,
    ):
        super().__init__()
        self._benchmark = benchmark
        self._deployment_name = deployment_name
        self._experiment_config = config
        self._language = config.runtime.language
        self._language_version = config.runtime.version
        self._architecture = self._experiment_config.architecture
        self._container_deployment = config.container_deployment
        self._benchmark_path = find_benchmark(self.benchmark, "benchmarks")
        if not self._benchmark_path:
            raise RuntimeError("Benchmark {benchmark} not found!".format(benchmark=self._benchmark))
        with open(os.path.join(self.benchmark_path, "config.json")) as json_file:
            self._benchmark_config: BenchmarkConfig = BenchmarkConfig.deserialize(
                json.load(json_file)
            )
        if self.language not in self.benchmark_config.languages:
            raise RuntimeError(
                "Benchmark {} not available for language {}".format(self.benchmark, self.language)
            )
        self._cache_client = cache_client
        self._docker_client = docker_client
        self._system_config = system_config
        self._hash_value = None
        self._output_dir = os.path.join(
            output_dir,
            f"{benchmark}_code",
            self._language.value,
            self._language_version,
            self._architecture,
            "container" if self._container_deployment else "package",
        )
        self._container_uri: Optional[str] = None

        # verify existence of function in cache
        self.query_cache()
        if config.update_code:
            self._is_cached_valid = False

        # Load input module

        self._benchmark_data_path = find_benchmark(self._benchmark, "benchmarks-data")
        self._benchmark_input_module = load_benchmark_input(self._benchmark_path)

        # Check if input has been processed
        self._input_processed: bool = False
        self._uses_storage: bool = False
        self._uses_nosql: bool = False

    """
        Compute MD5 hash of an entire directory.
    """

    @staticmethod
    def hash_directory(directory: str, deployment: str, language: str):

        hash_sum = hashlib.md5()
        FILES = {
            "python": ["*.py", "requirements.txt*"],
            "nodejs": ["*.js", "package.json"],
        }
        WRAPPERS = {"python": "*.py", "nodejs": "*.js"}
        NON_LANG_FILES = ["*.sh", "*.json"]
        selected_files = FILES[language] + NON_LANG_FILES
        for file_type in selected_files:
            for f in glob.glob(os.path.join(directory, file_type)):
                path = os.path.join(directory, f)
                with open(path, "rb") as opened_file:
                    hash_sum.update(opened_file.read())
        # wrappers
        wrappers = project_absolute_path(
            "benchmarks", "wrappers", deployment, language, WRAPPERS[language]
        )
        for f in glob.glob(wrappers):
            path = os.path.join(directory, f)
            with open(path, "rb") as opened_file:
                hash_sum.update(opened_file.read())
        return hash_sum.hexdigest()

    def serialize(self) -> dict:
        return {"size": self.code_size, "hash": self.hash}

    def query_cache(self):

        if self.container_deployment:
            self._code_package = self._cache_client.get_container(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.language_name,
                language_version=self.language_version,
                architecture=self.architecture,
            )
            if self._code_package is not None:
                self._container_uri = self._code_package["image-uri"]
        else:
            self._code_package = self._cache_client.get_code_package(
                deployment=self._deployment_name,
                benchmark=self._benchmark,
                language=self.language_name,
                language_version=self.language_version,
                architecture=self.architecture,
            )

        self._functions = self._cache_client.get_functions(
            deployment=self._deployment_name,
            benchmark=self._benchmark,
            language=self.language_name,
        )

        if self._code_package is not None:
            # compare hashes
            current_hash = self.hash
            old_hash = self._code_package["hash"]
            self._code_size = self._code_package["size"]
            self._is_cached = True
            self._is_cached_valid = current_hash == old_hash
        else:
            self._is_cached = False
            self._is_cached_valid = False

    def copy_code(self, output_dir):
        FILES = {
            "python": ["*.py", "requirements.txt*"],
            "nodejs": ["*.js", "package.json"],
        }
        path = os.path.join(self.benchmark_path, self.language_name)
        for file_type in FILES[self.language_name]:
            for f in glob.glob(os.path.join(path, file_type)):
                shutil.copy2(os.path.join(path, f), output_dir)
        # support node.js benchmarks with language specific packages
        nodejs_package_json = os.path.join(path, f"package.json.{self.language_version}")
        if os.path.exists(nodejs_package_json):
            shutil.copy2(nodejs_package_json, os.path.join(output_dir, "package.json"))

    def add_benchmark_data(self, output_dir):
        cmd = "/bin/bash {benchmark_path}/init.sh {output_dir} false {architecture}"
        paths = [
            self.benchmark_path,
            os.path.join(self.benchmark_path, self.language_name),
        ]
        for path in paths:
            if os.path.exists(os.path.join(path, "init.sh")):
                subprocess.run(
                    cmd.format(
                        benchmark_path=path,
                        output_dir=output_dir,
                        architecture=self._experiment_config._architecture,
                    ),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )

    def add_deployment_files(self, output_dir):
        handlers_dir = project_absolute_path(
            "benchmarks", "wrappers", self._deployment_name, self.language_name
        )
        handlers = [
            os.path.join(handlers_dir, file)
            for file in self._system_config.deployment_files(
                self._deployment_name, self.language_name
            )
        ]
        for file in handlers:
            shutil.copy2(file, os.path.join(output_dir))

    def add_deployment_package_python(self, output_dir):

        destination_file = f"requirements.txt.{self._language_version}"
        if not os.path.exists(os.path.join(output_dir, destination_file)):
            destination_file = "requirements.txt"

        # append to the end of requirements file
        with open(os.path.join(output_dir, destination_file), "a") as out:

            packages = self._system_config.deployment_packages(
                self._deployment_name, self.language_name
            )
            for package in packages:
                out.write(package)

            module_packages = self._system_config.deployment_module_packages(
                self._deployment_name, self.language_name
            )
            for bench_module in self._benchmark_config.modules:
                if bench_module.value in module_packages:
                    for package in module_packages[bench_module.value]:
                        out.write(package)

    def add_deployment_package_nodejs(self, output_dir):
        # modify package.json
        packages = self._system_config.deployment_packages(
            self._deployment_name, self.language_name
        )
        if len(packages):

            package_config = os.path.join(output_dir, f"package.json.{self._language_version}")
            if not os.path.exists(package_config):
                package_config = os.path.join(output_dir, "package.json")

            with open(package_config, "r") as package_file:
                package_json = json.load(package_file)
            for key, val in packages.items():
                package_json["dependencies"][key] = val
            with open(package_config, "w") as package_file:
                json.dump(package_json, package_file, indent=2)

    def add_deployment_package(self, output_dir):
        from sebs.faas.function import Language

        if self.language == Language.PYTHON:
            self.add_deployment_package_python(output_dir)
        elif self.language == Language.NODEJS:
            self.add_deployment_package_nodejs(output_dir)
        else:
            raise NotImplementedError

    @staticmethod
    def directory_size(directory: str):
        from pathlib import Path

        root = Path(directory)
        sizes = [f.stat().st_size for f in root.glob("**/*") if f.is_file()]
        return sum(sizes)

    def install_dependencies(self, output_dir):
        # do we have docker image for this run and language?
        if "build" not in self._system_config.docker_image_types(
            self._deployment_name, self.language_name
        ):
            self.logging.info(
                (
                    "There is no Docker build image for {deployment} run in {language}, "
                    "thus skipping the Docker-based installation of dependencies."
                ).format(deployment=self._deployment_name, language=self.language_name)
            )
        else:
            repo_name = self._system_config.docker_repository()
            unversioned_image_name = "build.{deployment}.{language}.{runtime}".format(
                deployment=self._deployment_name,
                language=self.language_name,
                runtime=self.language_version,
            )
            image_name = "{base_image_name}-{sebs_version}".format(
                base_image_name=unversioned_image_name,
                sebs_version=self._system_config.version(),
            )

            def ensure_image(name: str) -> None:
                try:
                    self._docker_client.images.get(repo_name + ":" + name)
                except docker.errors.ImageNotFound:
                    try:
                        self.logging.info(
                            "Docker pull of image {repo}:{image}".format(repo=repo_name, image=name)
                        )
                        self._docker_client.images.pull(repo_name, name)
                    except docker.errors.APIError:
                        raise RuntimeError(
                            "Docker pull of image {}:{} failed!".format(repo_name, name)
                        )

            try:
                ensure_image(image_name)
            except RuntimeError as e:
                self.logging.warning(
                    "Failed to ensure image {}, falling back to {}: {}".format(
                        image_name, unversioned_image_name, e
                    )
                )
                try:
                    ensure_image(unversioned_image_name)
                except RuntimeError:
                    raise
                # update `image_name` in the context to the fallback image name
                image_name = unversioned_image_name

            # Create set of mounted volumes unless Docker volumes are disabled
            if not self._experiment_config.check_flag("docker_copy_build_files"):
                volumes = {os.path.abspath(output_dir): {"bind": "/mnt/function", "mode": "rw"}}
                package_script = os.path.abspath(
                    os.path.join(self._benchmark_path, self.language_name, "package.sh")
                )
                # does this benchmark has package.sh script?
                if os.path.exists(package_script):
                    volumes[package_script] = {
                        "bind": "/mnt/function/package.sh",
                        "mode": "ro",
                    }

            # run Docker container to install packages
            PACKAGE_FILES = {"python": "requirements.txt", "nodejs": "package.json"}
            file = os.path.join(output_dir, PACKAGE_FILES[self.language_name])
            if os.path.exists(file):
                try:
                    self.logging.info(
                        "Docker build of benchmark dependencies in container "
                        "of image {repo}:{image}".format(repo=repo_name, image=image_name)
                    )
                    uid = os.getuid()
                    # Standard, simplest build
                    if not self._experiment_config.check_flag("docker_copy_build_files"):
                        self.logging.info(
                            "Docker mount of benchmark code from path {path}".format(
                                path=os.path.abspath(output_dir)
                            )
                        )
                        stdout = self._docker_client.containers.run(
                            "{}:{}".format(repo_name, image_name),
                            volumes=volumes,
                            environment={
                                "CONTAINER_UID": str(os.getuid()),
                                "CONTAINER_GID": str(os.getgid()),
                                "CONTAINER_USER": "docker_user",
                                "APP": self.benchmark,
                                "PLATFORM": self._deployment_name.upper(),
                                "TARGET_ARCHITECTURE": self._experiment_config._architecture,
                            },
                            remove=True,
                            stdout=True,
                            stderr=True,
                        )
                    # Hack to enable builds on platforms where Docker mounted volumes
                    # are not supported. Example: CircleCI docker environment
                    else:
                        container = self._docker_client.containers.run(
                            "{}:{}".format(repo_name, image_name),
                            environment={"APP": self.benchmark},
                            # user="1000:1000",
                            user=uid,
                            remove=True,
                            detach=True,
                            tty=True,
                            command="/bin/bash",
                        )
                        # copy application files
                        import tarfile

                        self.logging.info(
                            "Send benchmark code from path {path} to "
                            "Docker instance".format(path=os.path.abspath(output_dir))
                        )
                        tar_archive = os.path.join(output_dir, os.path.pardir, "function.tar")
                        with tarfile.open(tar_archive, "w") as tar:
                            for f in os.listdir(output_dir):
                                tar.add(os.path.join(output_dir, f), arcname=f)
                        with open(tar_archive, "rb") as data:
                            container.put_archive("/mnt/function", data.read())
                        # do the build step
                        exit_code, stdout = container.exec_run(
                            cmd="/bin/bash /sebs/installer.sh",
                            user="docker_user",
                            stdout=True,
                            stderr=True,
                        )
                        # copy updated code with package
                        data, stat = container.get_archive("/mnt/function")
                        with open(tar_archive, "wb") as f:
                            for chunk in data:
                                f.write(chunk)
                        with tarfile.open(tar_archive, "r") as tar:
                            tar.extractall(output_dir)
                            # docker packs the entire directory with basename function
                            for f in os.listdir(os.path.join(output_dir, "function")):
                                shutil.move(
                                    os.path.join(output_dir, "function", f),
                                    os.path.join(output_dir, f),
                                )
                            shutil.rmtree(os.path.join(output_dir, "function"))
                        container.stop()

                    # Pass to output information on optimizing builds.
                    # Useful for AWS where packages have to obey size limits.
                    for line in stdout.decode("utf-8").split("\n"):
                        if "size" in line:
                            self.logging.info("Docker build: {}".format(line))
                except docker.errors.ContainerError as e:
                    self.logging.error("Package build failed!")
                    self.logging.error(e)
                    self.logging.error(f"Docker mount volumes: {volumes}")
                    raise e

    def recalculate_code_size(self):
        self._code_size = Benchmark.directory_size(self._output_dir)
        return self._code_size

    def build(
        self,
        deployment_build_step: Callable[
            [str, str, str, str, str, bool, bool], Tuple[str, int, str]
        ],
    ) -> Tuple[bool, str, bool, str]:

        # Skip build if files are up to date and user didn't enforce rebuild
        if self.is_cached and self.is_cached_valid:
            self.logging.info(
                "Using cached benchmark {} at {}".format(self.benchmark, self.code_location)
            )
            if self.container_deployment:
                return False, self.code_location, self.container_deployment, self.container_uri

            return False, self.code_location, self.container_deployment, ""

        msg = (
            "no cached code package."
            if not self.is_cached
            else "cached code package is not up to date/build enforced."
        )
        self.logging.info("Building benchmark {}. Reason: {}".format(self.benchmark, msg))
        # clear existing cache information
        self._code_package = None

        # create directory to be deployed
        if os.path.exists(self._output_dir):
            shutil.rmtree(self._output_dir)
        os.makedirs(self._output_dir)

        self.copy_code(self._output_dir)
        self.add_benchmark_data(self._output_dir)
        self.add_deployment_files(self._output_dir)
        self.add_deployment_package(self._output_dir)
        self.install_dependencies(self._output_dir)

        self._code_location, self._code_size, self._container_uri = deployment_build_step(
            os.path.abspath(self._output_dir),
            self.language_name,
            self.language_version,
            self.architecture,
            self.benchmark,
            self.is_cached_valid,
            self.container_deployment,
        )
        self.logging.info(
            (
                "Created code package (source hash: {hash}), for run on {deployment}"
                + " with {language}:{runtime}"
            ).format(
                hash=self.hash,
                deployment=self._deployment_name,
                language=self.language_name,
                runtime=self.language_version,
            )
        )

        if self.is_cached:
            self._cache_client.update_code_package(self._deployment_name, self)
        else:
            self._cache_client.add_code_package(self._deployment_name, self)
        self.query_cache()

        return True, self._code_location, self._container_deployment, self._container_uri

    """
        Locates benchmark input generator, inspect how many storage buckets
        are needed and launches corresponding storage instance, if necessary.

        :param client: Deployment client
        :param benchmark:
        :param benchmark_path:
        :param size: Benchmark workload size
    """

    def prepare_input(
        self, system_resources: SystemResources, size: str, replace_existing: bool = False
    ):

        """
        Handle object storage buckets.
        """
        if hasattr(self._benchmark_input_module, "buckets_count"):

            buckets = self._benchmark_input_module.buckets_count()
            storage = system_resources.get_storage(replace_existing)
            input, output = storage.benchmark_data(self.benchmark, buckets)

            self._uses_storage = len(input) > 0 or len(output) > 0

            storage_func = storage.uploader_func
            bucket = storage.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        else:
            input = []
            output = []
            storage_func = None
            bucket = None

        """
            Handle key-value storage.
            This part is optional - only selected benchmarks implement this.
        """
        if hasattr(self._benchmark_input_module, "allocate_nosql"):

            nosql_storage = system_resources.get_nosql_storage()
            for name, table_properties in self._benchmark_input_module.allocate_nosql().items():
                nosql_storage.create_benchmark_tables(
                    self._benchmark,
                    name,
                    table_properties["primary_key"],
                    table_properties.get("secondary_key"),
                )

            self._uses_nosql = True
            nosql_func = nosql_storage.write_to_table
        else:
            nosql_func = None

        # buckets = mod.buckets_count()
        # storage.allocate_buckets(self.benchmark, buckets)
        # Get JSON and upload data as required by benchmark
        input_config = self._benchmark_input_module.generate_input(
            self._benchmark_data_path, size, bucket, input, output, storage_func, nosql_func
        )

        # Cache only once we data is in the cloud.
        if hasattr(self._benchmark_input_module, "buckets_count"):
            self._cache_client.update_storage(
                storage.deployment_name(),
                self._benchmark,
                {
                    "buckets": {
                        "input": storage.input_prefixes,
                        "output": storage.output_prefixes,
                        "input_uploaded": True,
                    }
                },
            )

        if hasattr(self._benchmark_input_module, "allocate_nosql"):
            nosql_storage.update_cache(self._benchmark)

        self._input_processed = True

        return input_config

    """
        This is used in experiments that modify the size of input package.
        This step allows to modify code package without going through the entire pipeline.
    """

    def code_package_modify(self, filename: str, data: bytes):

        if self.code_package_is_archive():
            self._update_zip(self.code_location, filename, data)
            new_size = self.code_package_recompute_size() / 1024.0 / 1024.0
            self.logging.info(f"Modified zip package {self.code_location}, new size {new_size} MB")
        else:
            raise NotImplementedError()

    """
        AWS: .zip file
        Azure: directory
    """

    def code_package_is_archive(self) -> bool:
        if os.path.isfile(self.code_location):
            extension = os.path.splitext(self.code_location)[1]
            return extension in [".zip"]
        return False

    def code_package_recompute_size(self) -> float:
        bytes_size = os.path.getsize(self.code_location)
        self._code_size = bytes_size
        return bytes_size

    #  https://stackoverflow.com/questions/25738523/how-to-update-one-file-inside-zip-file-using-python
    @staticmethod
    def _update_zip(zipname: str, filename: str, data: bytes):
        import zipfile
        import tempfile

        # generate a temp file
        tmpfd, tmpname = tempfile.mkstemp(dir=os.path.dirname(zipname))
        os.close(tmpfd)

        # create a temp copy of the archive without filename
        with zipfile.ZipFile(zipname, "r") as zin:
            with zipfile.ZipFile(tmpname, "w") as zout:
                zout.comment = zin.comment  # preserve the comment
                for item in zin.infolist():
                    if item.filename != filename:
                        zout.writestr(item, zin.read(item.filename))

        # replace with the temp archive
        os.remove(zipname)
        os.rename(tmpname, zipname)

        # now add filename with its new data
        with zipfile.ZipFile(zipname, mode="a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(filename, data)


"""
    The interface of `input` module of each benchmark.
    Useful for static type hinting with mypy.
"""


class BenchmarkModuleInterface:
    @staticmethod
    @abstractmethod
    def buckets_count() -> Tuple[int, int]:
        pass

    @staticmethod
    @abstractmethod
    def allocate_nosql() -> dict:
        pass

    @staticmethod
    @abstractmethod
    def generate_input(
        data_dir: str,
        size: str,
        benchmarks_bucket: Optional[str],
        input_paths: List[str],
        output_paths: List[str],
        upload_func: Optional[Callable[[int, str, str], None]],
        nosql_func: Optional[
            Callable[[str, str, dict, Tuple[str, str], Optional[Tuple[str, str]]], None]
        ],
    ) -> Dict[str, str]:
        pass


def load_benchmark_input(benchmark_path: str) -> BenchmarkModuleInterface:
    # Look for input generator file in the directory containing benchmark
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("input", os.path.join(benchmark_path, "input.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod  # type: ignore

import subprocess
import logging
import shutil
import json
import os
from typing import Tuple

from sebs import Benchmark
from sebs.faas import System, PersistentStorage
from sebs.faas.config import Config
from sebs.faas.function import Function
from .function import OpenwhiskFunction
from .config import OpenWhiskConfig
import yaml
import time


class OpenWhisk(System):
    _config: OpenWhiskConfig

    @property
    def config(self) -> Config:
        return self._config

    def get_storage(self, replace_existing: bool) -> PersistentStorage:
        pass

    def get_function(self, code_package: Benchmark) -> Function:
        pass

    def shutdown(self) -> None:
        pass

    @staticmethod
    def __run_check_process__(cmd: str, **kwargs) -> None:
        env = os.environ.copy()
        env = {**env, **kwargs}

        subprocess.run(
            cmd.split(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    @staticmethod
    def __check_installation__(app: str, cmd: str) -> None:
        try:
            logging.info('Checking {} installation...'.format(app))
            OpenWhisk.__run_check_process__(cmd)
            logging.info('Check successful, proceeding...')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error('Cannot find {}, aborting, reason: {}'.format(app, e))
            exit(1)

    @staticmethod
    def install_kind() -> None:
        try:
            logging.info('Installing kind...')
            OpenWhisk.__run_check_process__('go get sigs.k8s.io/kind@v0.8.1', GO111MODULE='on')
            logging.info('Kind has been installed')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error('Cannot install kind, reason: {}'.format(e))
            exit(1)

    @staticmethod
    def check_kind_installation() -> None:
        try:
            OpenWhisk.__run_check_process__('kind --version')
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.error('Cannot find kind executable, installing...')
            OpenWhisk.install_kind()

    @staticmethod
    def check_kubectl_installation() -> None:
        try:
            logging.info("Checking kubectl installation...")
            OpenWhisk.__run_check_process__('kubectl version --client=true')
            logging.info("Kubectl is installed")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.info("Kubectl is not installed, proceeding to install...")
            OpenWhisk.install_kubectl()

    @staticmethod
    def install_kubectl() -> None:
        try:
            logging.info('Installing kubectl...')
            home_path = os.environ['HOME']
            kubectl_path = '{}/.local/bin/kubectl'.format(home_path)
            OpenWhisk.__run_check_process__("curl -L -o {} "
                                            "https://storage.googleapis.com/kubernetes-release/release/v1.18.0/bin"
                                            "/linux/amd64/kubectl".format(kubectl_path))
            OpenWhisk.__run_check_process__("chmod +x {}".format(kubectl_path))
            logging.info('Kubectl has been installed')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error('Cannot install kubectl, reason: {}'.format(e))
            exit(1)

    @staticmethod
    def check_helm_installation() -> None:
        OpenWhisk.__check_installation__("helm", "helm version")

    @staticmethod
    def install_helm() -> None:
        try:
            logging.info('Installing helm...')
            helm_package = subprocess.run(
                "curl https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3".split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                "sh -".split(),
                input=helm_package.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            logging.info('Helm has been installed')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error('Cannot install helm, reason: {}'.format(e))
            exit(1)

    @staticmethod
    def check_kind_cluster() -> None:
        try:
            kind_clusters_process = subprocess.run(
                "kind get clusters".split(),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            kind_clusters = set(kind_clusters_process.stdout.decode('utf-8').split())
            if "kind" not in kind_clusters:
                logging.info("Creating kind cluster...")
                OpenWhisk.create_kind_cluster()
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot check kind cluster, reason: {}".format(e))

    @staticmethod
    def create_kind_cluster() -> None:
        try:
            OpenWhisk.__run_check_process__("kind create cluster --config openwhisk/kind-cluster.yaml")
            while True:
                nodes = subprocess.run(
                    "kubectl get nodes".split(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                node_grep = subprocess.run(
                    "grep kind".split(),
                    input=nodes.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                awk = subprocess.run(
                    ["awk", r'{print $2}'],
                    check=True,
                    input=node_grep.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                node_statuses = awk.stdout.decode('utf-8').split()
                if all(node_status == 'Ready' for node_status in node_statuses):
                    break
                time.sleep(1)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot create kind cluster. reason: {}".format(e))

    @staticmethod
    def get_worker_ip() -> str:
        try:
            logging.info('Attempting to find worker IP...')
            kind_worker_description = subprocess.run(
                "kubectl describe node kind-worker".split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            grep_internal_ip = subprocess.run(
                "grep InternalIP".split(),
                check=True,
                input=kind_worker_description.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            return grep_internal_ip.stdout.decode("utf-8").split()[1]
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Error during finding worker IP: {}".format(e))

    @staticmethod
    def label_nodes() -> None:
        def label_node(node: str, role: str) -> None:
            OpenWhisk.__run_check_process__("kubectl label node {} openwhisk-role={}".format(node, role))

        try:
            logging.info('Labelling nodes')
            label_node('kind-worker', 'core')
            label_node('kind-worker2', 'invoker')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error('Cannot label nodes, reason: {}'.format(e))

    @staticmethod
    def clone_openwhisk_chart() -> None:
        try:
            OpenWhisk.__run_check_process__(
                "git clone git@github.com:apache/openwhisk-deploy-kube.git /tmp/openwhisk-deploy-kube")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot clone openwhisk chart, reason: {}".format(e))

    @staticmethod
    def prepare_openwhisk_config() -> None:
        worker_ip = OpenWhisk.get_worker_ip()
        with open('openwhisk/mycluster_template.yaml', 'r') as openwhisk_config_template:
            data = yaml.unsafe_load(openwhisk_config_template)
            data['whisk']['ingress']['apiHostName'] = worker_ip
            data['whisk']['ingress']['apiHostPort'] = 31001
            data['nginx']['httpsNodePort'] = 31001
        if not os.path.exists('/tmp/openwhisk-deploy-kube/mycluster.yaml'):
            with open('/tmp/openwhisk-deploy-kube/mycluster.yaml', 'a+') as openwhisk_config:
                openwhisk_config.write(yaml.dump(data, default_flow_style=False))

    @staticmethod
    def check_openwhisk_installation(namespace: str) -> None:
        try:
            logging.info('Checking openwhisk installation.')
            namespaces = subprocess.run(
                "kubectl get namespaces".split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["grep", namespace],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                input=namespaces.stdout,
            )
            logging.info("Openwhisk installed!")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.info("Openwhisk is not installed, proceeding with installation...")
            OpenWhisk.helm_install()

    @staticmethod
    def helm_install() -> None:
        try:
            OpenWhisk.__run_check_process__("helm install owdev /tmp/openwhisk-deploy-kube/helm/openwhisk -n "
                                            "openwhisk --create-namespace -f /tmp/openwhisk-deploy-kube/mycluster.yaml")
            while True:
                pods = subprocess.run(
                    "kubectl get pods -n openwhisk".split(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                install_packages_grep = subprocess.run(
                    "grep install-packages".split(),
                    input=pods.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                install_packages_status = install_packages_grep.stdout.decode('utf-8').split()[2]
                if install_packages_status == 'Completed':
                    break
                time.sleep(1)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot install openwhisk, reason: {}".format(e))

    @staticmethod
    def expose_couchdb() -> None:
        try:
            OpenWhisk.__run_check_process__("kubectl apply -f openwhisk/couchdb-service.yaml")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot expose Couch DB, reason: {}".format(e))

    @staticmethod
    def install_openwhisk() -> None:
        OpenWhisk.check_kind_installation()
        OpenWhisk.check_kubectl_installation()
        OpenWhisk.check_helm_installation()
        OpenWhisk.check_kind_cluster()
        OpenWhisk.label_nodes()
        OpenWhisk.clone_openwhisk_chart()
        OpenWhisk.prepare_openwhisk_config()
        OpenWhisk.check_openwhisk_installation('openwhisk')
        OpenWhisk.expose_couchdb()

    @staticmethod
    def name() -> str:
        return "openwhisk"

    @staticmethod
    def get_openwhisk_url() -> str:
        ip = OpenWhisk.get_worker_ip()
        return '{}:{}'.format(ip, 31001)

    @staticmethod
    def get_couchdb_url() -> str:
        ip = OpenWhisk.get_worker_ip()
        return '{}:{}'.format(ip, 31201)

    @staticmethod
    def delete_cluster():
        try:
            logging.info('Deleting KinD cluster...')
            OpenWhisk.__run_check_process__('kind delete cluster')
            logging.info('KinD cluster deleted...')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Cannot delete cluster, reason: {}".format(e))

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:

        benchmark.build()
        node = 'nodejs'
        node_handler = 'handler.js'
        CONFIG_FILES = {
            'python': ['virtualenv', '__main__.py'],
            node: [node_handler, 'package.json', 'node_modules']
        }
        directory = benchmark.code_location
        package_config = CONFIG_FILES[benchmark.language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)

        # openwhisk needs main function to be named ina packaged.json
        if benchmark.language_name == node:
            filename = 'package.json'
            with open(filename, 'r') as f:
                data = json.load(f)
                data['main'] = node_handler

            os.remove(filename)
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)
        os.chdir(directory)
        subprocess.run(
            "zip -r {}.zip ./".format(benchmark.benchmark).split(),
            stdout=subprocess.DEVNULL,
        )
        benchmark_archive = "{}.zip".format(
            os.path.join(directory, benchmark.benchmark)
        )
        logging.info("Created {} archive".format(benchmark_archive))
        bytes_size = os.path.getsize(benchmark_archive)
        return benchmark_archive, bytes_size

    def get_function(self, code_package: Benchmark) -> Function:

        if (
                code_package.language_version
                not in self.system_config.supported_language_versions(self.name(), code_package.language_name)
        ):
            raise Exception(
                "Unsupported {language} version {version} in Openwhisk!".format(
                    language=code_package.language_name,
                    version=code_package.language_version,
                )
            )

        benchmark = code_package.benchmark
        func_name = code_package.cached_config["name"]
        code_location = code_package.code_location

        if code_package.is_cached and code_package.is_cached_valid:
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return OpenwhiskFunction(func_name)
        elif code_package.is_cached:

            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Run Openwhisk-specific part of building code.
            package, code_size = self.package_code(code_package)

            self.update_function(
                benchmark, func_name, package, code_size, timeout, memory
            )

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark, code_package.language_name, package, cached_cfg
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return OpenwhiskFunction(func_name)
        # no cached instance, create package and upload code
        else:

            language = code_package.language_name
            language_runtime = code_package.language_version
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Create function name, validation regexp if needed: \A([\w]|[\w][\w@ .-]*[\w@.-]+)\z
            func_name = "{}-{}-{}".format(benchmark, language, memory)

            package, code_size = self.package_code(code_package)
            # todo: check if function exists, if so delte otherwise create

            self.cache_client.add_function(
                deployment=self.name(),
                benchmark=benchmark,
                language=language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": language_runtime,
                    "memory": memory,
                    "timeout": timeout,
                    "hash": code_package.hash,
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets,
                    }
                },
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()
            return OpenwhiskFunction(func_name)

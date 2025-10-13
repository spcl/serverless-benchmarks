import logging
import os
import unittest
import testtools
import threading
from time import sleep
from typing import cast, Dict, Optional, Set, TYPE_CHECKING

from sebs.azure.cli import AzureCLI
from sebs.faas.function import Trigger
from sebs.utils import ColoredWrapper

if TYPE_CHECKING:
    from sebs import SeBS

benchmarks_python = [
    "110.dynamic-html",
    "120.uploader",
    "130.crud-api",
    "210.thumbnailer",
    "220.video-processing",
    "311.compression",
    "411.image-recognition",
    "501.graph-pagerank",
    "502.graph-mst",
    "503.graph-bfs",
    "504.dna-visualisation",
]
benchmarks_nodejs = ["110.dynamic-html", "120.uploader", "210.thumbnailer"]

architectures_aws = ["x64", "arm64"]
deployments_aws = ["package", "container"]

architectures_gcp = ["x64"]
deployments_gcp = ["package"]

architectures_azure = ["x64"]
deployments_azure = ["package"]

architectures_openwhisk = ["x64"]
deployments_openwhisk = ["container"]

# user-defined config passed during initialization
cloud_config: Optional[dict] = None


class TestSequenceMeta(type):
    def __init__(
        cls,
        name,
        bases,
        attrs,
        benchmarks,
        architectures,
        deployments,
        deployment_name,
        triggers,
    ):
        type.__init__(cls, name, bases, attrs)
        cls.deployment_name = deployment_name
        cls.triggers = triggers

    def __new__(
        mcs,
        name,
        bases,
        dict,
        benchmarks,
        architectures,
        deployments,
        deployment_name,
        triggers,
    ):
        def gen_test(benchmark_name, architecture, deployment_type):
            def test(self):
                log_name = (
                    f"Regression-{deployment_name}-{benchmark_name}-{deployment_type}"
                )
                logger = logging.getLogger(log_name)
                logger.setLevel(logging.INFO)
                logging_wrapper = ColoredWrapper(log_name, logger)

                self.experiment_config["architecture"] = architecture
                self.experiment_config["container_deployment"] = (
                    deployment_type == "container"
                )

                deployment_client = self.get_deployment(
                    benchmark_name, architecture, deployment_type
                )
                deployment_client.disable_rich_output()

                logging_wrapper.info(
                    f"Begin regression test of {benchmark_name} on {deployment_client.name()}. "
                    f"Architecture {architecture}, deployment type: {deployment_type}."
                )

                experiment_config = self.client.get_experiment_config(
                    self.experiment_config
                )

                benchmark = self.client.get_benchmark(
                    benchmark_name, deployment_client, experiment_config
                )
                input_config = benchmark.prepare_input(
                    deployment_client.system_resources,
                    size="test",
                    replace_existing=experiment_config.update_storage,
                )

                func = deployment_client.get_function(
                    benchmark, deployment_client.default_function_name(benchmark)
                )

                failure = False
                for trigger_type in triggers:
                    if len(func.triggers(trigger_type)) > 0:
                        trigger = func.triggers(trigger_type)[0]
                    else:
                        trigger = deployment_client.create_trigger(func, trigger_type)
                        """
                            sleep 5 seconds - on some cloud systems the triggers might
                            not be available immediately.
                            for example, AWS tends to throw "not exist" on newly created
                            API gateway
                        """
                        sleep(5)
                    # Synchronous invoke
                    try:
                        ret = trigger.sync_invoke(input_config)
                        if ret.stats.failure:
                            failure = True
                            logging_wrapper.error(
                                f"{benchmark_name} fail on trigger: {trigger_type}"
                            )
                        else:
                            logging_wrapper.info(
                                f"{benchmark_name} success on trigger: {trigger_type}"
                            )
                    except RuntimeError:
                        failure = True
                        logging_wrapper.error(
                            f"{benchmark_name} fail on trigger: {trigger_type}"
                        )
                deployment_client.shutdown()
                if failure:
                    raise RuntimeError(f"Test of {benchmark_name} failed!")

            return test

        for benchmark in benchmarks:
            for architecture in architectures:
                for deployment_type in deployments:
                    # for trigger in triggers:
                    test_name = f"test_{deployment_name}_{benchmark}"
                    test_name += f"_{architecture}_{deployment_type}"
                    dict[test_name] = gen_test(benchmark, architecture, deployment_type)

        dict["lock"] = threading.Lock()
        dict["cfg"] = None
        return type.__new__(mcs, name, bases, dict)


class AWSTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    architectures=architectures_aws,
    deployments=deployments_aws,
    deployment_name="aws",
    triggers=[Trigger.TriggerType.LIBRARY, Trigger.TriggerType.HTTP],
):
    @property
    def typename(self) -> str:
        return "AWSTestPython"

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "aws"
        assert cloud_config

        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        with AWSTestSequencePython.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


class AWSTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    architectures=architectures_aws,
    deployments=deployments_aws,
    deployment_name="aws",
    triggers=[Trigger.TriggerType.LIBRARY, Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "aws"
        assert cloud_config
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )
        with AWSTestSequenceNodejs.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


class AzureTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    architectures=architectures_azure,
    deployments=deployments_azure,
    deployment_name="azure",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "azure"
        assert cloud_config
        with AzureTestSequencePython.lock:
            if not AzureTestSequencePython.cfg:
                AzureTestSequencePython.cfg = self.client.get_deployment_config(
                    cloud_config["deployment"],
                    logging_filename=os.path.join(
                        self.client.output_dir,
                        f"regression_{deployment_name}_{benchmark_name}_{architecture}.log",
                    ),
                )

            if not hasattr(AzureTestSequencePython, "cli"):
                AzureTestSequencePython.cli = AzureCLI(
                    self.client.config, self.client.docker_client
                )

            f = f"regression_{deployment_name}_{benchmark_name}_"
            f += f"{architecture}_{deployment_type}.log"
            deployment_client = self.client.get_deployment(
                cloud_config,
                logging_filename=os.path.join(self.client.output_dir, f),
                deployment_config=AzureTestSequencePython.cfg,
            )
            deployment_client.system_resources.initialize_cli(
                cli=AzureTestSequencePython.cli, login=True
            )
            deployment_client.initialize(resource_prefix="regr")
            return deployment_client


class AzureTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    architectures=architectures_azure,
    deployments=deployments_azure,
    deployment_name="azure",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "azure"
        assert cloud_config
        with AzureTestSequenceNodejs.lock:
            if not AzureTestSequenceNodejs.cfg:
                AzureTestSequenceNodejs.cfg = self.client.get_deployment_config(
                    cloud_config["deployment"],
                    logging_filename=f"regression_{deployment_name}_{benchmark_name}.log",
                )

            if not hasattr(AzureTestSequenceNodejs, "cli"):
                AzureTestSequenceNodejs.cli = AzureCLI(
                    self.client.config, self.client.docker_client
                )

            f = f"regression_{deployment_name}_{benchmark_name}_"
            f += f"{architecture}_{deployment_type}.log"
            deployment_client = self.client.get_deployment(
                cloud_config,
                logging_filename=os.path.join(self.client.output_dir, f),
                deployment_config=AzureTestSequencePython.cfg,
            )
            deployment_client.system_resources.initialize_cli(
                cli=AzureTestSequenceNodejs.cli
            )
            deployment_client.initialize(resource_prefix="regr")
            return deployment_client


class GCPTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    architectures=architectures_gcp,
    deployments=deployments_gcp,
    deployment_name="gcp",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "gcp"
        assert cloud_config
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )
        with GCPTestSequencePython.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


class GCPTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    architectures=architectures_gcp,
    deployments=deployments_gcp,
    deployment_name="gcp",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "gcp"
        assert cloud_config
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )
        with GCPTestSequenceNodejs.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


class OpenWhiskTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    architectures=architectures_openwhisk,
    deployments=deployments_openwhisk,
    deployment_name="openwhisk",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "openwhisk"
        assert cloud_config

        config_copy = cloud_config.copy()
        config_copy["experiments"]["architecture"] = architecture
        config_copy["experiments"]["container_deployment"] = (
            deployment_type == "container"
        )

        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            config_copy,
            logging_filename=os.path.join(self.client.output_dir, f),
        )
        with OpenWhiskTestSequencePython.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


class OpenWhiskTestSequenceNodejs(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_nodejs,
    architectures=architectures_openwhisk,
    deployments=deployments_openwhisk,
    deployment_name="openwhisk",
    triggers=[Trigger.TriggerType.HTTP],
):
    def get_deployment(self, benchmark_name, architecture, deployment_type):
        deployment_name = "openwhisk"
        assert cloud_config

        config_copy = cloud_config.copy()
        config_copy["experiments"]["architecture"] = architecture
        config_copy["experiments"]["container_deployment"] = (
            deployment_type == "container"
        )

        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            config_copy,
            logging_filename=os.path.join(self.client.output_dir, f),
        )
        with OpenWhiskTestSequenceNodejs.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


# https://stackoverflow.com/questions/22484805/a-simple-working-example-for-testtools-concurrentstreamtestsuite
class TracingStreamResult(testtools.StreamResult):
    all_correct: bool
    output: Dict[str, bytes] = {}

    def __init__(self):
        self.all_correct = True
        self.success = set()
        self.failures = set()

    # no way to directly access test instance from here
    def status(self, *args, **kwargs):
        self.all_correct = self.all_correct and (
            kwargs["test_status"] in ["inprogress", "success"]
        )

        bench, arch, deployment_type = kwargs["test_id"].split("_")[-3:None]
        test_name = f"{bench}, {arch}, {deployment_type}"
        if not kwargs["test_status"]:
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            print("\n-------------\n")
            print("{0[test_id]}: {0[test_status]}".format(kwargs))
            print(
                "{0[test_id]}: {1}".format(
                    kwargs, self.output[kwargs["test_id"]].decode()
                )
            )
            print("\n-------------\n")
            self.failures.add(test_name)
        elif kwargs["test_status"] == "success":
            self.success.add(test_name)


def filter_out_benchmarks(
    benchmark: str,
    deployment_name: str,
    language: str,
    language_version: str,
    architecture: str,
) -> bool:
    # fmt: off
    if (deployment_name == "aws" and language == "python"
            and language_version in ["3.9", "3.10", "3.11"]):
        return "411.image-recognition" not in benchmark

    if (deployment_name == "aws" and architecture == "arm64"):
        return "411.image-recognition" not in benchmark

    if (deployment_name == "gcp" and language == "python"
            and language_version in ["3.8", "3.9", "3.10", "3.11", "3.12"]):
        return "411.image-recognition" not in benchmark
    # fmt: on

    return True


def regression_suite(
    sebs_client: "SeBS",
    experiment_config: dict,
    providers: Set[str],
    deployment_config: dict,
    benchmark_name: Optional[str] = None,
):
    suite = unittest.TestSuite()
    global cloud_config
    cloud_config = deployment_config

    language = experiment_config["runtime"]["language"]
    language_version = experiment_config["runtime"]["version"]
    architecture = experiment_config["architecture"]

    if "aws" in providers:
        assert "aws" in cloud_config["deployment"]
        if language == "python":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequencePython)
            )
        elif language == "nodejs":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequenceNodejs)
            )
    if "gcp" in providers:
        assert "gcp" in cloud_config["deployment"]
        if language == "python":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequencePython)
            )
        elif language == "nodejs":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequenceNodejs)
            )
    if "azure" in providers:
        assert "azure" in cloud_config["deployment"]
        if language == "python":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    AzureTestSequencePython
                )
            )
        elif language == "nodejs":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    AzureTestSequenceNodejs
                )
            )
    if "openwhisk" in providers:
        assert "openwhisk" in cloud_config["deployment"]
        if language == "python":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    OpenWhiskTestSequencePython
                )
            )
        elif language == "nodejs":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(
                    OpenWhiskTestSequenceNodejs
                )
            )

    tests = []
    # mypy is confused here
    for case in suite:
        for test in case:  # type: ignore
            # skip
            test_name = cast(unittest.TestCase, test)._testMethodName

            # Remove unsupported benchmarks
            if not filter_out_benchmarks(
                test_name,
                test.deployment_name,  # type: ignore
                language,  # type: ignore
                language_version,
                architecture,  # type: ignore
            ):
                print(f"Skip test {test_name} - not supported.")
                continue

            # Use only a selected benchmark
            if not benchmark_name or (benchmark_name and benchmark_name in test_name):
                test.client = sebs_client  # type: ignore
                test.experiment_config = experiment_config.copy()  # type: ignore
                tests.append(test)
            else:
                print(f"Skip test {test_name}")

    concurrent_suite = testtools.ConcurrentStreamTestSuite(
        lambda: ((test, None) for test in tests)
    )
    result = TracingStreamResult()
    result.startTestRun()
    concurrent_suite.run(result)
    result.stopTestRun()
    print(f"Succesfully executed {len(result.success)} out of {len(tests)} functions")
    for suc in result.success:
        print(f"- {suc}")
    if len(result.failures):
        print(
            f"Failures when executing {len(result.failures)} out of {len(tests)} functions"
        )
        for failure in result.failures:
            print(f"- {failure}")

    if hasattr(AzureTestSequenceNodejs, "cli"):
        AzureTestSequenceNodejs.cli.shutdown()
    if hasattr(AzureTestSequencePython, "cli"):
        AzureTestSequencePython.cli.shutdown()

    return not result.all_correct

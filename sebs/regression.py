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
    from sebs.faas.system import System as FaaSSystem # For type hinting get_deployment return


"""
This module defines test sequences for regression testing SeBS on various
cloud providers (AWS, Azure, GCP, OpenWhisk). It uses a metaclass
`TestSequenceMeta` to dynamically generate test methods for different benchmarks,
programming languages, architectures, and deployment types (package/container).

The main entry point is `regression_suite`, which constructs a test suite
based on user configuration and runs it using `testtools.ConcurrentStreamTestSuite`
for parallel execution of tests.
"""

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
        deployments: List[str],
        deployment_name: str,
        triggers: List[Trigger.TriggerType],
    ):
        """
        Initialize the TestSequenceMeta metaclass.

        Stores deployment name and trigger types as class attributes, which are
        then accessible by the generated test methods and other class methods.

        :param name: Name of the class being created.
        :param bases: Base classes of the class being created.
        :param attrs: Attributes of the class being created.
        :param benchmarks: List of benchmark names to generate tests for.
        :param architectures: List of architectures to test.
        :param deployments: List of deployment types (e.g., "package", "container").
        :param deployment_name: Name of the cloud deployment (e.g., "aws").
        :param triggers: List of Trigger.TriggerType enums to test.
        """
        type.__init__(cls, name, bases, attrs)
        cls.deployment_name = deployment_name
        cls.triggers = triggers

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        attrs: dict, # Renamed from dict to attrs to avoid keyword conflict
        benchmarks: List[str],
        architectures: List[str],
        deployments: List[str],
        deployment_name: str,
        triggers: List[Trigger.TriggerType],
    ):
        """
        Dynamically create test methods for each combination of benchmark,
        architecture, and deployment type.

        Each generated test method (e.g., `test_aws_010.sleep_x64_package`)
        will perform a regression test for that specific configuration by:
        1. Setting up a logger and experiment configuration.
        2. Obtaining and initializing a deployment client.
        3. Preparing the benchmark and its input.
        4. Invoking the function using specified trigger types.
        5. Reporting success or failure.

        A class-level lock (`cls.lock`) and a configuration placeholder (`cls.cfg`)
        are also added to the new class, intended for managing shared resources
        like a common Azure CLI instance across tests in a sequence.

        :param name: Name of the class to be created.
        :param bases: Base classes.
        :param attrs: Class attributes dictionary to which test methods will be added.
        :param benchmarks: List of benchmark names.
        :param architectures: List of architectures.
        :param deployments: List of deployment types.
        :param deployment_name: Name of the cloud deployment.
        :param triggers: List of trigger types to test.
        :return: A new class with dynamically generated test methods.
        """
        def gen_test(benchmark_name_arg: str, architecture_arg: str, deployment_type_arg: str):
            # Inner test function, forms the body of each generated test method
            def test(self: unittest.TestCase): # `self` here is an instance of the test class
                log_name = f"Regression-{deployment_name}-{benchmark_name_arg}-{architecture_arg}-{deployment_type_arg}"
                logger = logging.getLogger(log_name)
                logger.setLevel(logging.INFO)
                logging_wrapper = ColoredWrapper(log_name, logger)

                self.experiment_config["architecture"] = architecture
                self.experiment_config["container_deployment"] = deployment_type == "container"

                deployment_client = self.get_deployment(
                    benchmark_name, architecture, deployment_type
                )
                deployment_client.disable_rich_output()

                logging_wrapper.info(
                    f"Begin regression test of {benchmark_name} on {deployment_client.name()}. "
                    f"Architecture {architecture}, deployment type: {deployment_type}."
                )

                experiment_config = self.client.get_experiment_config(self.experiment_config)

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
                        logging_wrapper.error(f"{benchmark_name} fail on trigger: {trigger_type}")
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

        attrs["lock"] = threading.Lock() # Class-level lock for shared resources
        attrs["cfg"] = None # Placeholder for shared deployment config (e.g. Azure CLI)
        return type.__new__(mcs, name, bases, attrs)


class AWSTestSequencePython(
    unittest.TestCase,
    metaclass=TestSequenceMeta,
    benchmarks=benchmarks_python,
    architectures=architectures_aws,
    deployments=deployments_aws,
    deployment_name="aws",
    triggers=[Trigger.TriggerType.LIBRARY, Trigger.TriggerType.HTTP],
):
    """
    Test sequence for Python benchmarks on AWS.
    Dynamically generates test methods for combinations of Python benchmarks,
    AWS architectures (x64, arm64), and deployment types (package, container).
    Tests both Library and HTTP triggers.
    """
    @property
    def typename(self) -> str:
        """Return a type name for this test sequence, used for identification."""
        return "AWSTestPython"

    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for AWS for a specific test case.

        :param benchmark_name: Name of the benchmark being tested.
        :param architecture: CPU architecture for the test.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized AWS deployment client (an instance of `sebs.aws.AWS`).
        """
        deployment_name = "aws" # Ensure correct deployment name is used
        assert cloud_config is not None, "Global cloud_config not set for regression tests"

        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Node.js benchmarks on AWS.
    Dynamically generates test methods for combinations of Node.js benchmarks,
    AWS architectures, and deployment types. Tests both Library and HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for AWS for a specific test case.

        :param benchmark_name: Name of the benchmark being tested.
        :param architecture: CPU architecture for the test.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized AWS deployment client.
        """
        deployment_name = "aws"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"
        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Python benchmarks on Azure.
    Dynamically generates test methods for Python benchmarks on Azure.
    Manages a shared AzureCLI instance to optimize Azure operations across tests.
    Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for Azure.
        Manages a shared AzureCLI instance for tests within this sequence.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized Azure deployment client.
        """
        deployment_name = "azure"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"
        with AzureTestSequencePython.lock: # type: ignore
            if not AzureTestSequencePython.cfg: # type: ignore
                AzureTestSequencePython.cfg = self.client.get_deployment_config( # type: ignore
                    cloud_config["deployment"]["azure"], # Pass the 'azure' sub-dictionary
                    logging_filename=os.path.join(
                        self.client.output_dir, # type: ignore
                        f"regression_{deployment_name}_shared_cli_config.log", # Log for shared components
                    ),
                )

            if not hasattr(AzureTestSequencePython, "cli"): # type: ignore
                # Ensure system_config is passed to AzureCLI if it expects SeBSConfig
                azure_system_config = self.client.config # type: ignore
                AzureTestSequencePython.cli = AzureCLI( # type: ignore
                    azure_system_config, self.client.docker_client # type: ignore
                )

            log_file_name = f"regression_{deployment_name}_{benchmark_name}_"
            log_file_name += f"{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Node.js benchmarks on Azure.
    Dynamically generates test methods for Node.js benchmarks on Azure.
    Manages a shared AzureCLI instance. Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for Azure.
        Manages a shared AzureCLI instance for tests within this sequence.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized Azure deployment client.
        """
        deployment_name = "azure"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"
        with AzureTestSequenceNodejs.lock: # type: ignore
            if not AzureTestSequenceNodejs.cfg: # type: ignore
                AzureTestSequenceNodejs.cfg = self.client.get_deployment_config( # type: ignore
                    cloud_config["deployment"]["azure"], # Pass the 'azure' sub-dictionary
                    logging_filename=f"regression_{deployment_name}_shared_cli_config.log",
                )

            if not hasattr(AzureTestSequenceNodejs, "cli"): # type: ignore
                azure_system_config = self.client.config # type: ignore
                AzureTestSequenceNodejs.cli = AzureCLI( # type: ignore
                    azure_system_config, self.client.docker_client # type: ignore
                )

            log_file_name = f"regression_{deployment_name}_{benchmark_name}_"
            log_file_name += f"{architecture}_{deployment_type}.log"
            deployment_client = self.client.get_deployment(
                cloud_config,
                logging_filename=os.path.join(self.client.output_dir, f),
                deployment_config=AzureTestSequencePython.cfg,
            )
            deployment_client.system_resources.initialize_cli(cli=AzureTestSequenceNodejs.cli)
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
    """
    Test sequence for Python benchmarks on GCP.
    Dynamically generates test methods for Python benchmarks on GCP.
    Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for GCP.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized GCP deployment client.
        """
        deployment_name = "gcp"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"
        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Node.js benchmarks on GCP.
    Dynamically generates test methods for Node.js benchmarks on GCP.
    Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for GCP.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized GCP deployment client.
        """
        deployment_name = "gcp"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"
        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Python benchmarks on OpenWhisk.
    Dynamically generates test methods for Python benchmarks on OpenWhisk.
    Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for OpenWhisk.

        Modifies a copy of the global cloud configuration to set architecture
        and container deployment type for this specific test.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized OpenWhisk deployment client.
        """
        deployment_name = "openwhisk"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"

        # Create a deep copy to avoid modifying the global config for other tests
        config_copy = json.loads(json.dumps(cloud_config))
        config_copy["experiments"]["architecture"] = architecture
        # OpenWhisk in SeBS typically uses container deployment
        config_copy["experiments"]["container_deployment"] = (deployment_type == "container")

        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    """
    Test sequence for Node.js benchmarks on OpenWhisk.
    Dynamically generates test methods for Node.js benchmarks on OpenWhisk.
    Tests HTTP triggers.
    """
    def get_deployment(self, benchmark_name: str, architecture: str, deployment_type: str) -> "FaaSSystem":
        """
        Get and initialize a deployment client for OpenWhisk.

        Modifies a copy of the global cloud configuration to set architecture
        and container deployment type for this specific test.

        :param benchmark_name: Name of the benchmark.
        :param architecture: CPU architecture.
        :param deployment_type: Deployment type ("package" or "container").
        :return: Initialized OpenWhisk deployment client.
        """
        deployment_name = "openwhisk"
        assert cloud_config is not None, "Global cloud_config not set for regression tests"

        config_copy = json.loads(json.dumps(cloud_config))
        config_copy["experiments"]["architecture"] = architecture
        config_copy["experiments"]["container_deployment"] = (deployment_type == "container")

        log_file_name = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
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
    output: Dict[str, bytes] # Stores output bytes for failed tests, keyed by test_id

    def __init__(self):
        """Initialize TracingStreamResult, setting all_correct to True and preparing sets for results."""
        super().__init__() # Ensure parent StreamResult is initialized
        self.all_correct = True
        self.success: Set[str] = set()
        self.failures: Set[str] = set()
        self.output: Dict[str, bytes] = {}


    # no way to directly access test instance from here
    def status(self, *args, **kwargs):
        """
        Process the status of a test execution.

        Updates `all_correct` flag, records successes and failures, and captures
        output for failed tests.

        :param args: Positional arguments passed by testtools.
        :param kwargs: Keyword arguments including 'test_id', 'test_status', 'file_bytes'.
        """
        super().status(*args, **kwargs) # Call parent status method
        
        current_test_status = kwargs.get("test_status")
        test_id = kwargs.get("test_id", "unknown_test")

        self.all_correct = self.all_correct and (current_test_status in [None, "inprogress", "success"])

        # Extract a more readable test name if possible (e.g., from test_id)
        try:
            # Assuming test_id format like test_deployment_benchmark_arch_deploytype
            parts = test_id.split('_')
            if len(parts) >= 5: # test_method_deployment_benchmark_arch_deploytype
                # Example: benchmark_name from parts[-4], arch from parts[-2], deploy_type from parts[-1]
                # This parsing is fragile and depends heavily on test_name format from TestSequenceMeta
                test_name_short = f"{parts[-3]}, {parts[-2]}, {parts[-1]}"
            else:
                test_name_short = test_id
        except Exception:
            test_name_short = test_id

        if current_test_status is None: # File bytes are being streamed
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs.get("file_bytes", b"")
        elif current_test_status == "fail":
            print("\n-------------\n")
            print(f"{test_id}: {current_test_status}")
            # Ensure output for this test_id is decoded if it exists
            failure_output = self.output.get(test_id, b"").decode(errors='replace')
            print(f"{test_id}: {failure_output}")
            print("\n-------------\n")
            self.failures.add(test_name_short)
        elif current_test_status == "success":
            self.success.add(test_name_short)
            # Clean up output for successful tests to save memory
            if test_id in self.output:
                del self.output[test_id]


def filter_out_benchmarks(
    benchmark_name_in_test_id: str, # The full test_id string, e.g. test_aws_010.sleep_x64_package
    deployment_name: str,
    language: str,
    language_version: str,
    architecture: str,
) -> bool:
    """
    Filter out benchmarks that are known to be unsupported or problematic
    for specific deployment configurations.

    :param benchmark_name_in_test_id: The full name of the test method, which includes benchmark name.
    :param deployment_name: Name of the FaaS deployment.
    :param language: Programming language.
    :param language_version: Language runtime version.
    :param architecture: CPU architecture.
    :return: True if the benchmark should be run, False if it should be filtered out.
    """
    # fmt: off
    # Example: Filter out 411.image-recognition for newer Python versions on AWS
    # The benchmark_name_in_test_id needs to be parsed to get the actual benchmark identifier
    # For simplicity, assuming benchmark_name_in_test_id contains the benchmark string directly.
    # A more robust way would be to pass the benchmark identifier itself.
    if (deployment_name == "aws" and language == "python"
            and language_version in ["3.9", "3.10", "3.11", "3.12"]): # Added 3.12 as example
        if "411.image-recognition" in benchmark_name_in_test_id:
            return False

    if (deployment_name == "aws" and architecture == "arm64"):
        if "411.image-recognition" in benchmark_name_in_test_id: # Example filter for ARM
            return False

    if (deployment_name == "gcp" and language == "python"
            and language_version in ["3.8", "3.9", "3.10", "3.11", "3.12"]):
        if "411.image-recognition" in benchmark_name_in_test_id:
            return False
    # fmt: on

    return True # Default to run if no filter matches


def regression_suite(
    sebs_client: "SeBS",
    experiment_config: dict, # This is likely ExperimentConfig instance or dict representation
    providers_to_test: Set[str], # Renamed from providers
    deployment_user_config: dict, # Renamed from deployment_config
    target_benchmark_name: Optional[str] = None, # Renamed from benchmark_name
) -> bool:
    """
    Construct and run a regression test suite.

    Dynamically creates test cases for specified providers, languages, benchmarks, etc.,
    based on the loaded SeBS and experiment configurations. Uses `testtools` for
    concurrent test execution and collects results.

    :param sebs_client: The main SeBS client instance.
    :param experiment_config: Dictionary representing the experiment configuration.
    :param providers_to_test: Set of FaaS provider names to include in the test suite.
    :param deployment_user_config: Dictionary with deployment-specific configurations from user.
    :param target_benchmark_name: Optional name of a single benchmark to run. If None, runs all.
    :return: True if any test failed, False if all tests passed.
    """
    suite = unittest.TestSuite()
    global cloud_config # Store the user's deployment config globally for test cases to access
    cloud_config = deployment_user_config

    # Extract common parameters from experiment_config
    runtime_lang = experiment_config.get("runtime", {}).get("language")
    runtime_version = experiment_config.get("runtime", {}).get("version")
    target_architecture = experiment_config.get("architecture")

    if not all([runtime_lang, runtime_version, target_architecture]):
        logging.error("Missing runtime language, version, or architecture in experiment_config.")
        return True # Indicate failure due to bad config

    # Add test sequences for selected providers and languages
    if "aws" in providers_to_test:
        assert "aws" in deployment_user_config["deployment"], "AWS config missing in deployment section"
        if runtime_lang == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequencePython))
        elif runtime_lang == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequenceNodejs))
    
    if "gcp" in providers_to_test:
        assert "gcp" in deployment_user_config["deployment"], "GCP config missing in deployment section"
        if runtime_lang == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequencePython))
        elif runtime_lang == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequenceNodejs))
   
    if "azure" in providers_to_test:
        assert "azure" in deployment_user_config["deployment"], "Azure config missing in deployment section"
        if runtime_lang == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequencePython))
        elif runtime_lang == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequenceNodejs))
    
    if "openwhisk" in providers_to_test:
        assert "openwhisk" in deployment_user_config["deployment"], "OpenWhisk config missing in deployment section"
        if runtime_lang == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(OpenWhiskTestSequencePython))
        elif runtime_lang == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(OpenWhiskTestSequenceNodejs))

    # Filter tests based on benchmark_name and unsupported configurations
    filtered_tests = []
    for test_case_class_instance in suite: # Iterating through TestSuite gives TestCase instances
        for individual_test_method in test_case_class_instance: # Iterating through TestCase gives test methods
            test_method_name = cast(unittest.TestCase, individual_test_method)._testMethodName
            
            # Get deployment_name from the test class itself (set by metaclass)
            current_test_deployment_name = getattr(individual_test_method.__class__, 'deployment_name', 'unknown')

            if not filter_out_benchmarks(
                test_method_name, # Contains benchmark identifier
                current_test_deployment_name,
                runtime_lang,
                runtime_version,
                target_architecture,
            ):
                print(f"Skipping test {test_method_name} - filtered out as unsupported/problematic.")
                continue

            if not target_benchmark_name or (target_benchmark_name and target_benchmark_name in test_method_name):
                # Inject SeBS client and experiment config into each test instance
                setattr(individual_test_method, 'client', sebs_client)
                setattr(individual_test_method, 'experiment_config', experiment_config.copy())
                filtered_tests.append(individual_test_method)
            else:
                print(f"Skipping test {test_method_name} - does not match target benchmark '{target_benchmark_name}'.")
    
    if not filtered_tests:
        logging.warning("No tests selected to run after filtering. Check configuration and benchmark name.")
        return False # No failures if no tests run

    # Run the filtered tests concurrently
    concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((test, None) for test in filtered_tests))
    stream_result_collector = TracingStreamResult()
    stream_result_collector.startTestRun()
    concurrent_suite.run(stream_result_collector)
    stream_result_collector.stopTestRun()

    print(f"\nSuccessfully executed {len(stream_result_collector.success)} out of {len(filtered_tests)} tests:")
    for success_info in sorted(list(stream_result_collector.success)):
        print(f"  - PASSED: {success_info}")
    
    if stream_result_collector.failures:
        print(f"\nFailures in {len(stream_result_collector.failures)} out of {len(filtered_tests)} tests:")
        for failure_info in sorted(list(stream_result_collector.failures)):
            print(f"  - FAILED: {failure_info}")
            # Detailed output for failures is already printed by TracingStreamResult.status

    # Shutdown shared resources like AzureCLI if they were initialized by test sequences
    if hasattr(AzureTestSequenceNodejs, "cli") and AzureTestSequenceNodejs.cli: # type: ignore
        AzureTestSequenceNodejs.cli.shutdown() # type: ignore
    if hasattr(AzureTestSequencePython, "cli") and AzureTestSequencePython.cli: # type: ignore
        AzureTestSequencePython.cli.shutdown() # type: ignore
    
    return not stream_result_collector.all_correct

"""Regression testing framework for serverless benchmarks across cloud providers.

This module provides a flexible testing framework to validate benchmark functionality
across multiple cloud providers, runtimes, architectures, and deployment methods.
It automatically generates test cases for each valid combination and runs them
concurrently to efficiently validate the system.

The module supports:
- AWS Lambda
- Azure Functions
- Google Cloud Functions
- OpenWhisk
- Multiple runtime languages (Python, Node.js)
- Multiple architectures (x64, arm64)
- Different deployment types (package, container)
- Different trigger types (HTTP, library)
"""

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

# List of Python benchmarks available for regression testing
benchmarks_python = [
    "110.dynamic-html",  # Dynamic HTML generation
    "120.uploader",  # File upload handling
    "130.crud-api",  # CRUD API implementation
    "210.thumbnailer",  # Image thumbnail generation
    "220.video-processing",  # Video processing
    "311.compression",  # Data compression
    "411.image-recognition",  # ML-based image recognition
    "501.graph-pagerank",  # Graph PageRank algorithm
    "502.graph-mst",  # Graph minimum spanning tree
    "503.graph-bfs",  # Graph breadth-first search
    "504.dna-visualisation",  # DNA visualization
]

# List of Node.js benchmarks available for regression testing
benchmarks_nodejs = ["110.dynamic-html", "120.uploader", "210.thumbnailer"]

# AWS-specific configurations
architectures_aws = ["x64", "arm64"]  # Supported architectures
deployments_aws = ["package", "container"]  # Deployment types

# GCP-specific configurations
architectures_gcp = ["x64"]  # Supported architectures
deployments_gcp = ["package"]  # Deployment types

# Azure-specific configurations
architectures_azure = ["x64"]  # Supported architectures
deployments_azure = ["package"]  # Deployment types

# OpenWhisk-specific configurations
architectures_openwhisk = ["x64"]  # Supported architectures
deployments_openwhisk = ["container"]  # Deployment types

# User-defined config passed during initialization, set in regression_suite()
cloud_config: Optional[dict] = None


class TestSequenceMeta(type):
    """Metaclass for dynamically generating regression test cases.

    This metaclass automatically generates test methods for all combinations of
    benchmark, architecture, and deployment type. Each test method deploys and
    executes a specific benchmark on a specific cloud provider with a specific
    configuration.

    The generated tests follow a naming convention:
    test_{provider}_{benchmark}_{architecture}_{deployment_type}
    """

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
        """Initialize the test class with deployment information.

        Args:
            cls: The class being created
            name: The name of the class
            bases: Base classes
            attrs: Class attributes
            benchmarks: List of benchmark names to test
            architectures: List of architectures to test (e.g., x64, arm64)
            deployments: List of deployment types to test (e.g., package, container)
            deployment_name: Name of the cloud provider (e.g., aws, azure)
            triggers: List of trigger types to test (e.g., HTTP, library)
        """
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
        """Create a new test class with dynamically generated test methods.

        Args:
            mcs: The metaclass
            name: The name of the class
            bases: Base classes
            dict: Class attributes dictionary
            benchmarks: List of benchmark names to test
            architectures: List of architectures to test
            deployments: List of deployment types to test
            deployment_name: Name of the cloud provider
            triggers: List of trigger types to test

        Returns:
            A new test class with dynamically generated test methods
        """

        def gen_test(benchmark_name, architecture, deployment_type):
            """Generate a test function for a specific benchmark configuration.

            Args:
                benchmark_name: Name of the benchmark to test
                architecture: Architecture to test on
                deployment_type: Deployment type to use

            Returns:
                A test function that deploys and executes the benchmark
            """

            def test(self):
                """Test function that deploys and executes a benchmark.

                This function:
                1. Sets up logging
                2. Gets a deployment client
                3. Configures the benchmark
                4. Deploys the function
                5. Invokes the function with different triggers
                6. Verifies the function execution

                Raises:
                    RuntimeError: If the benchmark execution fails
                """
                log_name = f"Regression-{deployment_name}-{benchmark_name}-{deployment_type}"
                logger = logging.getLogger(log_name)
                logger.setLevel(logging.INFO)
                logging_wrapper = ColoredWrapper(log_name, logger)

                # Configure experiment settings
                self.experiment_config["architecture"] = architecture
                self.experiment_config["container_deployment"] = deployment_type == "container"

                # Get deployment client for the specific cloud provider
                deployment_client = self.get_deployment(
                    benchmark_name, architecture, deployment_type
                )
                deployment_client.disable_rich_output()

                logging_wrapper.info(
                    f"Begin regression test of {benchmark_name} on {deployment_client.name()}. "
                    f"Architecture {architecture}, deployment type: {deployment_type}."
                )

                # Get experiment configuration and deploy the benchmark
                experiment_config = self.client.get_experiment_config(self.experiment_config)
                benchmark = self.client.get_benchmark(
                    benchmark_name, deployment_client, experiment_config
                )

                # Prepare input data for the benchmark
                input_config = benchmark.prepare_input(
                    deployment_client.system_resources,
                    size="test",
                    replace_existing=experiment_config.update_storage,
                )

                # Get or create the function
                func = deployment_client.get_function(
                    benchmark, deployment_client.default_function_name(benchmark)
                )

                # Test each trigger type
                failure = False
                for trigger_type in triggers:
                    if len(func.triggers(trigger_type)) > 0:
                        trigger = func.triggers(trigger_type)[0]
                    else:
                        trigger = deployment_client.create_trigger(func, trigger_type)
                        # Sleep to allow trigger creation to propagate
                        # Some cloud systems (e.g., AWS API Gateway) need time
                        # before the trigger is ready to use
                        sleep(5)

                    # Synchronous invoke to test function
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

                # Clean up resources
                deployment_client.shutdown()

                # Report overall test result
                if failure:
                    raise RuntimeError(f"Test of {benchmark_name} failed!")

            return test

        # Generate test methods for each combination
        for benchmark in benchmarks:
            for architecture in architectures:
                for deployment_type in deployments:
                    test_name = f"test_{deployment_name}_{benchmark}"
                    test_name += f"_{architecture}_{deployment_type}"
                    dict[test_name] = gen_test(benchmark, architecture, deployment_type)

        # Add shared resources
        dict["lock"] = threading.Lock()  # Lock for thread-safe initialization
        dict["cfg"] = None  # Shared configuration
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
    """Test suite for Python benchmarks on AWS Lambda.

    This test class runs all Python benchmarks on AWS Lambda,
    using various architectures (x64, arm64) and deployment types
    (package, container). Each test uses both library and HTTP triggers.

    Attributes:
        benchmarks: List of Python benchmarks to test
        architectures: List of AWS architectures to test (x64, arm64)
        deployments: List of deployment types to test (package, container)
        deployment_name: Cloud provider name ("aws")
        triggers: List of trigger types to test (LIBRARY, HTTP)
    """

    @property
    def typename(self) -> str:
        """Get the type name of this test suite.

        Returns:
            A string identifier for this test suite
        """
        return "AWSTestPython"

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an AWS deployment client for the specified configuration.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64, arm64)
            deployment_type: Deployment type (package, container)

        Returns:
            An initialized AWS deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "aws"
        assert cloud_config, "Cloud configuration is required"

        # Create a log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
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
    """Test suite for Node.js benchmarks on AWS Lambda.

    This test class runs all Node.js benchmarks on AWS Lambda,
    using various architectures (x64, arm64) and deployment types
    (package, container). Each test uses both library and HTTP triggers.

    Attributes:
        benchmarks: List of Node.js benchmarks to test
        architectures: List of AWS architectures to test (x64, arm64)
        deployments: List of deployment types to test (package, container)
        deployment_name: Cloud provider name ("aws")
        triggers: List of trigger types to test (LIBRARY, HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an AWS deployment client for the specified configuration.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64, arm64)
            deployment_type: Deployment type (package, container)

        Returns:
            An initialized AWS deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "aws"
        assert cloud_config, "Cloud configuration is required"

        # Create a log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
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
    """Test suite for Python benchmarks on Azure Functions.

    This test class runs all Python benchmarks on Azure Functions,
    using x64 architecture and package deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Python benchmarks to test
        architectures: List of Azure architectures to test (x64)
        deployments: List of deployment types to test (package)
        deployment_name: Cloud provider name ("azure")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an Azure deployment client for the specified configuration.

        This method handles special Azure setup requirements, including:
        - Caching deployment configuration to avoid recreating it for each test
        - Initializing the Azure CLI for resource management
        - Setting up system resources with proper authentication

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (package)

        Returns:
            An initialized Azure deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "azure"
        assert cloud_config, "Cloud configuration is required"

        with AzureTestSequencePython.lock:
            # Cache the deployment configuration for reuse across tests
            if not AzureTestSequencePython.cfg:
                AzureTestSequencePython.cfg = self.client.get_deployment_config(
                    cloud_config["deployment"],
                    logging_filename=os.path.join(
                        self.client.output_dir,
                        f"regression_{deployment_name}_{benchmark_name}_{architecture}.log",
                    ),
                )

            # Initialize Azure CLI if not already done
            if not hasattr(AzureTestSequencePython, "cli"):
                AzureTestSequencePython.cli = AzureCLI(
                    self.client.config, self.client.docker_client
                )

            # Create log file name and get deployment client
            f = f"regression_{deployment_name}_{benchmark_name}_"
            f += f"{architecture}_{deployment_type}.log"
            deployment_client = self.client.get_deployment(
                cloud_config,
                logging_filename=os.path.join(self.client.output_dir, f),
                deployment_config=AzureTestSequencePython.cfg,
            )

            # Initialize CLI with login and setup resources
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
    """Test suite for Node.js benchmarks on Azure Functions.

    This test class runs all Node.js benchmarks on Azure Functions,
    using x64 architecture and package deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Node.js benchmarks to test
        architectures: List of Azure architectures to test (x64)
        deployments: List of deployment types to test (package)
        deployment_name: Cloud provider name ("azure")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an Azure deployment client for the specified configuration.

        This method handles special Azure setup requirements, including:
        - Caching deployment configuration to avoid recreating it for each test
        - Initializing the Azure CLI for resource management
        - Setting up system resources

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (package)

        Returns:
            An initialized Azure deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "azure"
        assert cloud_config, "Cloud configuration is required"

        with AzureTestSequenceNodejs.lock:
            # Cache the deployment configuration for reuse across tests
            if not AzureTestSequenceNodejs.cfg:
                AzureTestSequenceNodejs.cfg = self.client.get_deployment_config(
                    cloud_config["deployment"],
                    logging_filename=f"regression_{deployment_name}_{benchmark_name}.log",
                )

            # Initialize Azure CLI if not already done
            if not hasattr(AzureTestSequenceNodejs, "cli"):
                AzureTestSequenceNodejs.cli = AzureCLI(
                    self.client.config, self.client.docker_client
                )

            # Create log file name and get deployment client
            f = f"regression_{deployment_name}_{benchmark_name}_"
            f += f"{architecture}_{deployment_type}.log"
            deployment_client = self.client.get_deployment(
                cloud_config,
                logging_filename=os.path.join(self.client.output_dir, f),
                deployment_config=AzureTestSequencePython.cfg,  # Note: This uses Python config
            )

            # Initialize CLI and setup resources (no login needed - reuses Python session)
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
    """Test suite for Python benchmarks on Google Cloud Functions.

    This test class runs all Python benchmarks on Google Cloud Functions,
    using x64 architecture and package deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Python benchmarks to test
        architectures: List of GCP architectures to test (x64)
        deployments: List of deployment types to test (package)
        deployment_name: Cloud provider name ("gcp")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get a GCP deployment client for the specified configuration.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (package)

        Returns:
            An initialized Google Cloud Functions deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "gcp"
        assert cloud_config, "Cloud configuration is required"

        # Create log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
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
    """Test suite for Node.js benchmarks on Google Cloud Functions.

    This test class runs all Node.js benchmarks on Google Cloud Functions,
    using x64 architecture and package deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Node.js benchmarks to test
        architectures: List of GCP architectures to test (x64)
        deployments: List of deployment types to test (package)
        deployment_name: Cloud provider name ("gcp")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get a GCP deployment client for the specified configuration.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (package)

        Returns:
            An initialized Google Cloud Functions deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "gcp"
        assert cloud_config, "Cloud configuration is required"

        # Create log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            cloud_config,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
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
    """Test suite for Python benchmarks on OpenWhisk.

    This test class runs all Python benchmarks on OpenWhisk,
    using x64 architecture and container deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Python benchmarks to test
        architectures: List of OpenWhisk architectures to test (x64)
        deployments: List of deployment types to test (container)
        deployment_name: Cloud provider name ("openwhisk")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an OpenWhisk deployment client for the specified configuration.

        This method handles special OpenWhisk setup requirements, including
        creating a modified configuration with architecture and deployment
        type settings.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (container)

        Returns:
            An initialized OpenWhisk deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "openwhisk"
        assert cloud_config, "Cloud configuration is required"

        # Create a copy of the config and set architecture and deployment type
        config_copy = cloud_config.copy()
        config_copy["experiments"]["architecture"] = architecture
        config_copy["experiments"]["container_deployment"] = deployment_type == "container"

        # Create log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            config_copy,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
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
    """Test suite for Node.js benchmarks on OpenWhisk.

    This test class runs all Node.js benchmarks on OpenWhisk,
    using x64 architecture and container deployment. Each test uses
    HTTP triggers.

    Attributes:
        benchmarks: List of Node.js benchmarks to test
        architectures: List of OpenWhisk architectures to test (x64)
        deployments: List of deployment types to test (container)
        deployment_name: Cloud provider name ("openwhisk")
        triggers: List of trigger types to test (HTTP)
    """

    def get_deployment(self, benchmark_name, architecture, deployment_type):
        """Get an OpenWhisk deployment client for the specified configuration.

        This method handles special OpenWhisk setup requirements, including
        creating a modified configuration with architecture and deployment
        type settings.

        Args:
            benchmark_name: Name of the benchmark to deploy
            architecture: Architecture to deploy on (x64)
            deployment_type: Deployment type (container)

        Returns:
            An initialized OpenWhisk deployment client

        Raises:
            AssertionError: If cloud_config is not set
        """
        deployment_name = "openwhisk"
        assert cloud_config, "Cloud configuration is required"

        # Create a copy of the config and set architecture and deployment type
        config_copy = cloud_config.copy()
        config_copy["experiments"]["architecture"] = architecture
        config_copy["experiments"]["container_deployment"] = deployment_type == "container"

        # Create log file name based on test parameters
        f = f"regression_{deployment_name}_{benchmark_name}_{architecture}_{deployment_type}.log"
        deployment_client = self.client.get_deployment(
            config_copy,
            logging_filename=os.path.join(self.client.output_dir, f),
        )

        # Synchronize resource initialization with a lock
        with OpenWhiskTestSequenceNodejs.lock:
            deployment_client.initialize(resource_prefix="regr")
        return deployment_client


# Stream result handler for concurrent test execution
# Based on https://stackoverflow.com/questions/22484805/a-simple-working-example-for-testtools-concurrentstreamtestsuite
class TracingStreamResult(testtools.StreamResult):
    """Stream result handler for concurrent test execution.

    This class captures test execution results and maintains running state
    for all tests. It tracks successful tests, failed tests, and collects
    test output for reporting.

    Attributes:
        all_correct: Whether all tests have passed
        output: Dictionary mapping test IDs to their output bytes
        success: Set of test names that succeeded
        failures: Set of test names that failed
    """

    all_correct: bool
    output: Dict[str, bytes] = {}

    def __init__(self):
        """Initialize a new stream result handler.

        Sets up initial state for tracking test results.
        """
        self.all_correct = True
        self.success = set()
        self.failures = set()

    def status(self, *args, **kwargs):
        """Process a test status update.

        This method is called by the test runner to report on test progress
        and results. It parses test IDs, collects output, and tracks success/failure.

        Args:
            *args: Variable length argument list (not used)
            **kwargs: Keyword arguments including test_id, test_status, and file_bytes
        """
        # Update overall test status (only inprogress and success states are considered passing)
        self.all_correct = self.all_correct and (kwargs["test_status"] in ["inprogress", "success"])

        # Extract benchmark, architecture, and deployment type from test ID
        bench, arch, deployment_type = kwargs["test_id"].split("_")[-3:None]
        test_name = f"{bench}, {arch}, {deployment_type}"

        if not kwargs["test_status"]:
            # Collect test output
            test_id = kwargs["test_id"]
            if test_id not in self.output:
                self.output[test_id] = b""
            self.output[test_id] += kwargs["file_bytes"]
        elif kwargs["test_status"] == "fail":
            # Handle test failure
            print("\n-------------\n")
            print("{0[test_id]}: {0[test_status]}".format(kwargs))
            print("{0[test_id]}: {1}".format(kwargs, self.output[kwargs["test_id"]].decode()))
            print("\n-------------\n")
            self.failures.add(test_name)
        elif kwargs["test_status"] == "success":
            # Track successful tests
            self.success.add(test_name)


def filter_out_benchmarks(
    benchmark: str,
    deployment_name: str,
    language: str,
    language_version: str,
    architecture: str,
) -> bool:
    """Filter out benchmarks that are not supported on specific platforms.

    Some benchmarks are not compatible with certain runtime environments due
    to memory constraints, unsupported libraries, or other limitations.
    This function identifies those incompatible combinations.

    Args:
        benchmark: The benchmark name to check
        deployment_name: Cloud provider name (aws, azure, gcp, openwhisk)
        language: Runtime language (python, nodejs)
        language_version: Language version (e.g., "3.9", "3.10")
        architecture: CPU architecture (x64, arm64)

    Returns:
        bool: True if the benchmark should be included, False to filter it out
    """
    # fmt: off
    # Filter out image recognition on newer Python versions on AWS
    if (deployment_name == "aws" and language == "python"
            and language_version in ["3.9", "3.10", "3.11"]):
        return "411.image-recognition" not in benchmark

    # Filter out image recognition on ARM architecture on AWS
    if (deployment_name == "aws" and architecture == "arm64"):
        return "411.image-recognition" not in benchmark

    # Filter out image recognition on newer Python versions on GCP
    if (deployment_name == "gcp" and language == "python"
            and language_version in ["3.8", "3.9", "3.10", "3.11", "3.12"]):
        return "411.image-recognition" not in benchmark
    # fmt: on

    # All other benchmarks are supported
    return True


def regression_suite(
    sebs_client: "SeBS",
    experiment_config: dict,
    providers: Set[str],
    deployment_config: dict,
    benchmark_name: Optional[str] = None,
):
    """Create and run a regression test suite for specified cloud providers.

    This function creates a test suite with all applicable test combinations for
    the selected cloud providers and runtime configuration. It then runs the tests
    concurrently and reports on successes and failures.

    Args:
        sebs_client: The SeBS client instance
        experiment_config: Configuration dictionary for the experiment
        providers: Set of cloud provider names to test
        deployment_config: Configuration dictionary for deployments
        benchmark_name: Optional name of a specific benchmark to test

    Returns:
        bool: True if any tests failed, False if all tests succeeded

    Raises:
        AssertionError: If a requested provider is not in the deployment config
    """
    # Create the test suite
    suite = unittest.TestSuite()

    # Make cloud_config available to test classes
    global cloud_config
    cloud_config = deployment_config

    # Extract runtime configuration
    language = experiment_config["runtime"]["language"]
    language_version = experiment_config["runtime"]["version"]
    architecture = experiment_config["architecture"]

    # Add AWS tests if requested
    if "aws" in providers:
        assert (
            "aws" in cloud_config["deployment"]
        ), "AWS provider requested but not in deployment config"
        if language == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequencePython))
        elif language == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSTestSequenceNodejs))

    # Add GCP tests if requested
    if "gcp" in providers:
        assert (
            "gcp" in cloud_config["deployment"]
        ), "GCP provider requested but not in deployment config"
        if language == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequencePython))
        elif language == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(GCPTestSequenceNodejs))

    # Add Azure tests if requested
    if "azure" in providers:
        assert (
            "azure" in cloud_config["deployment"]
        ), "Azure provider requested but not in deployment config"
        if language == "python":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequencePython))
        elif language == "nodejs":
            suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AzureTestSequenceNodejs))

    # Add OpenWhisk tests if requested
    if "openwhisk" in providers:
        assert (
            "openwhisk" in cloud_config["deployment"]
        ), "OpenWhisk provider requested but not in deployment config"
        if language == "python":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(OpenWhiskTestSequencePython)
            )
        elif language == "nodejs":
            suite.addTest(
                unittest.defaultTestLoader.loadTestsFromTestCase(OpenWhiskTestSequenceNodejs)
            )

    # Prepare the list of tests to run
    tests = []
    # mypy is confused here about the type
    for case in suite:
        for test in case:  # type: ignore
            # Get the test method name
            test_name = cast(unittest.TestCase, test)._testMethodName

            # Filter out unsupported benchmarks
            if not filter_out_benchmarks(
                test_name,
                test.deployment_name,  # type: ignore
                language,
                language_version,
                architecture,  # type: ignore
            ):
                print(f"Skip test {test_name} - not supported.")
                continue

            # Filter by benchmark name if specified
            if not benchmark_name or (benchmark_name and benchmark_name in test_name):
                # Set up test instance with client and config
                test.client = sebs_client  # type: ignore
                test.experiment_config = experiment_config.copy()  # type: ignore
                tests.append(test)
            else:
                print(f"Skip test {test_name}")

    # Create a concurrent test suite for parallel execution
    concurrent_suite = testtools.ConcurrentStreamTestSuite(lambda: ((test, None) for test in tests))
    result = TracingStreamResult()

    # Run the tests
    result.startTestRun()
    concurrent_suite.run(result)
    result.stopTestRun()

    # Report results
    print(f"Succesfully executed {len(result.success)} out of {len(tests)} functions")
    for suc in result.success:
        print(f"- {suc}")
    if len(result.failures):
        print(f"Failures when executing {len(result.failures)} out of {len(tests)} functions")
        for failure in result.failures:
            print(f"- {failure}")

    # Clean up resources
    if hasattr(AzureTestSequenceNodejs, "cli"):
        AzureTestSequenceNodejs.cli.shutdown()
    if hasattr(AzureTestSequencePython, "cli"):
        AzureTestSequencePython.cli.shutdown()

    # Return True if any test failed
    return not result.all_correct

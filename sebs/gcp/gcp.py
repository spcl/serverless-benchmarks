"""Google Cloud Platform (GCP) serverless system implementation.

This module provides the main GCP implementation for the Serverless Benchmarking Suite,
including function deployment, management, monitoring, and resource allocation.
It integrates with Google Cloud Functions, Cloud Storage, Cloud Monitoring, and
Cloud Logging to provide comprehensive serverless benchmarking capabilities.

The module handles:
- Function creation, updating, and lifecycle management
- Code packaging and deployment to Cloud Functions
- HTTP and library trigger management
- Performance metrics collection via Cloud Monitoring
- Execution logs retrieval via Cloud Logging
- Cold start enforcement for benchmarking
- Storage bucket management for code deployment

Classes:
    GCP: Main system class implementing the FaaS System interface

Example:
    Basic GCP system initialization:
    
        config = GCPConfig(credentials, resources)
        gcp_system = GCP(system_config, config, cache, docker_client, logging_handlers)
        gcp_system.initialize()
"""

import docker
import os
import logging
import re
import shutil
import time
import math
import zipfile
from datetime import datetime, timezone
from typing import cast, Dict, Optional, Tuple, List, Type

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import google.cloud.monitoring_v3 as monitoring_v3

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.benchmark import Benchmark
from sebs.faas.function import Function, FunctionConfig, Trigger
from sebs.faas.config import Resources
from sebs.faas.system import System
from sebs.gcp.config import GCPConfig
from sebs.gcp.resources import GCPSystemResources
from sebs.gcp.storage import GCPStorage
from sebs.gcp.function import GCPFunction
from sebs.utils import LoggingHandlers


class GCP(System):
    """Google Cloud Platform serverless system implementation.
    
    Provides complete integration with Google Cloud Functions including deployment,
    monitoring, logging, and resource management. Handles code packaging, function
    lifecycle management, trigger creation, and performance metrics collection.
    
    Attributes:
        _config: GCP-specific configuration including credentials and region
        function_client: Google Cloud Functions API client
        cold_start_counter: Counter for enforcing cold starts in benchmarking
        logging_handlers: Logging configuration for status reporting
    """
    
    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logging_handlers: LoggingHandlers,
    ) -> None:
        """Initialize GCP serverless system.
        
        Args:
            system_config: General SeBS system configuration
            config: GCP-specific configuration with credentials and settings
            cache_client: Cache instance for storing function and resource state
            docker_client: Docker client for container operations (if needed)
            logging_handlers: Logging configuration for status reporting
        """
        super().__init__(
            system_config,
            cache_client,
            docker_client,
            GCPSystemResources(
                system_config, config, cache_client, docker_client, logging_handlers
            ),
        )
        self._config = config
        self.logging_handlers = logging_handlers

    @property
    def config(self) -> GCPConfig:
        """Get the GCP configuration instance.
        
        Returns:
            GCP configuration with credentials and region settings
        """
        return self._config

    @staticmethod
    def name() -> str:
        """Get the platform name identifier.
        
        Returns:
            Platform name string 'gcp'
        """
        return "gcp"

    @staticmethod
    def typename() -> str:
        """Get the platform type name for display.
        
        Returns:
            Platform type string 'GCP'
        """
        return "GCP"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Get the function class type for this platform.
        
        Returns:
            GCPFunction class type
        """
        return GCPFunction

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None) -> None:
        """Initialize the GCP system for function deployment and management.
        
        Sets up the Cloud Functions API client and initializes system resources
        including storage buckets and other required infrastructure.
        
        Args:
            config: Additional system-specific configuration parameters
            resource_prefix: Optional prefix for resource naming to avoid conflicts
        """
        self.function_client = build("cloudfunctions", "v1", cache_discovery=False)
        self.initialize_resources(select_prefix=resource_prefix)

    def get_function_client(self):
        """Get the Google Cloud Functions API client.
        
        Returns:
            Initialized Cloud Functions API client
        """
        return self.function_client

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """Generate a default function name for the given benchmark.
        
        Creates a standardized function name using resource ID, benchmark name,
        language, and version information. Formats the name according to GCP
        Cloud Functions naming requirements.
        
        Args:
            code_package: Benchmark package containing metadata
            resources: Optional resource configuration for ID generation
            
        Returns:
            Formatted function name suitable for GCP Cloud Functions
        """
        # Create function name
        resource_id = resources.resources_id if resources else self.config.resources.resources_id
        func_name = "sebs-{}-{}-{}-{}".format(
            resource_id,
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
        )
        return GCP.format_function_name(func_name)

    @staticmethod
    def format_function_name(func_name: str) -> str:
        """Format function name according to GCP Cloud Functions requirements.
        
        Converts function names to comply with GCP naming rules by replacing
        hyphens and dots with underscores. GCP functions must begin with a letter
        and can only contain letters, numbers, and underscores.
        
        Args:
            func_name: Raw function name to format
            
        Returns:
            GCP-compliant function name
        """
        # GCP functions must begin with a letter
        # however, we now add by default `sebs` in the beginning
        func_name = func_name.replace("-", "_")
        func_name = func_name.replace(".", "_")
        return func_name

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int, str]:
        """Package benchmark code for GCP Cloud Functions deployment.
        
        Transforms the benchmark code directory structure to meet GCP Cloud Functions
        requirements. Creates a zip archive with the appropriate handler file naming
        and directory structure for the specified language runtime.
        
        The packaging process:
        1. Creates a 'function' subdirectory for benchmark sources
        2. Renames handler files to GCP-required names (handler.py -> main.py)
        3. Creates a zip archive for deployment
        4. Restores original file structure
        
        Args:
            directory: Path to the benchmark code directory
            language_name: Programming language (python, nodejs)
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (x86_64, arm64)
            benchmark: Benchmark name for archive naming
            is_cached: Whether this package is from cache
            container_deployment: Whether to use container deployment (unsupported)
            
        Returns:
            Tuple of (archive_path, archive_size_bytes, container_uri)
            
        Raises:
            NotImplementedError: If container_deployment is True
        """

        container_uri = ""

        if container_deployment:
            raise NotImplementedError("Container Deployment is not supported in GCP")

        CONFIG_FILES = {
            "python": ["handler.py", ".python_packages"],
            "nodejs": ["handler.js", "node_modules"],
        }
        HANDLER = {
            "python": ("handler.py", "main.py"),
            "nodejs": ("handler.js", "index.js"),
        }
        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        # rename handler function.py since in gcp it has to be caled main.py
        old_name, new_name = HANDLER[language_name]
        old_path = os.path.join(directory, old_name)
        new_path = os.path.join(directory, new_name)
        shutil.move(old_path, new_path)

        """
            zip the whole directory (the zip-file gets uploaded to gcp later)

            Note that the function GCP.recursive_zip is slower than the use of e.g.
            `utils.execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True)`
            or `shutil.make_archive(benchmark_archive, direcory, directory)`
            But both of the two alternatives need a chance of directory
            (shutil.make_archive does the directorychange internaly)
            which leads to a "race condition" when running several benchmarks
            in parallel, since a change of the current directory is NOT Thread specfic.
        """
        benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark))
        GCP.recursive_zip(directory, benchmark_archive)
        logging.info("Created {} archive".format(benchmark_archive))

        bytes_size = os.path.getsize(benchmark_archive)
        mbytes = bytes_size / 1024.0 / 1024.0
        logging.info("Zip archive size {:2f} MB".format(mbytes))

        # rename the main.py back to handler.py
        shutil.move(new_path, old_path)

        return os.path.join(directory, "{}.zip".format(benchmark)), bytes_size, container_uri

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> "GCPFunction":
        """Create a new GCP Cloud Function or update existing one.
        
        Deploys a benchmark as a Cloud Function, handling code upload to Cloud Storage,
        function creation with proper configuration, and IAM policy setup for
        unauthenticated invocations. If the function already exists, updates it instead.
        
        Args:
            code_package: Benchmark package with code and configuration
            func_name: Name for the Cloud Function
            container_deployment: Whether to use container deployment (unsupported)
            container_uri: Container image URI (unused for GCP)
            
        Returns:
            GCPFunction instance representing the deployed function
            
        Raises:
            NotImplementedError: If container_deployment is True
            RuntimeError: If function creation or IAM configuration fails
        """

        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in GCP")

        package = code_package.code_location
        benchmark = code_package.benchmark
        language_runtime = code_package.language_version
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory
        code_bucket: Optional[str] = None
        storage_client = self._system_resources.get_storage()
        location = self.config.region
        project_name = self.config.project_name
        function_cfg = FunctionConfig.from_benchmark(code_package)
        architecture = function_cfg.architecture.value

        code_package_name = cast(str, os.path.basename(package))
        code_package_name = f"{architecture}-{code_package_name}"
        code_bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        code_prefix = os.path.join(benchmark, code_package_name)
        storage_client.upload(code_bucket, package, code_prefix)

        self.logging.info("Uploading function {} code to {}".format(func_name, code_bucket))

        full_func_name = GCP.get_full_function_name(project_name, location, func_name)
        get_req = self.function_client.projects().locations().functions().get(name=full_func_name)

        try:
            get_req.execute()
        except HttpError:

            envs = self._generate_function_envs(code_package)

            create_req = (
                self.function_client.projects()
                .locations()
                .functions()
                .create(
                    location="projects/{project_name}/locations/{location}".format(
                        project_name=project_name, location=location
                    ),
                    body={
                        "name": full_func_name,
                        "entryPoint": "handler",
                        "runtime": code_package.language_name + language_runtime.replace(".", ""),
                        "availableMemoryMb": memory,
                        "timeout": str(timeout) + "s",
                        "httpsTrigger": {},
                        "ingressSettings": "ALLOW_ALL",
                        "sourceArchiveUrl": "gs://" + code_bucket + "/" + code_prefix,
                        "environmentVariables": envs,
                    },
                )
            )
            create_req.execute()
            self.logging.info(f"Function {func_name} has been created!")

            allow_unauthenticated_req = (
                self.function_client.projects()
                .locations()
                .functions()
                .setIamPolicy(
                    resource=full_func_name,
                    body={
                        "policy": {
                            "bindings": [
                                {"role": "roles/cloudfunctions.invoker", "members": ["allUsers"]}
                            ]
                        }
                    },
                )
            )

            # Avoid infinite loop
            MAX_RETRIES = 5
            counter = 0
            while counter < MAX_RETRIES:
                try:
                    allow_unauthenticated_req.execute()
                    break
                except HttpError:

                    self.logging.info(
                        "Sleeping for 5 seconds because the created functions is not yet available!"
                    )
                    time.sleep(5)
                    counter += 1
            else:
                raise RuntimeError(
                    f"Failed to configure function {full_func_name} "
                    "for unauthenticated invocations!"
                )

            self.logging.info(f"Function {func_name} accepts now unauthenticated invocations!")

            function = GCPFunction(
                func_name, benchmark, code_package.hash, function_cfg, code_bucket
            )
        else:
            # if result is not empty, then function does exists
            self.logging.info("Function {} exists on GCP, update the instance.".format(func_name))

            function = GCPFunction(
                name=func_name,
                benchmark=benchmark,
                code_package_hash=code_package.hash,
                cfg=function_cfg,
                bucket=code_bucket,
            )
            self.update_function(function, code_package, container_deployment, container_uri)

        # Add LibraryTrigger to a new function
        from sebs.gcp.triggers import LibraryTrigger

        trigger = LibraryTrigger(func_name, self)
        trigger.logging_handlers = self.logging_handlers
        function.add_trigger(trigger)

        return function

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """Create a trigger for the given function.
        
        Creates HTTP triggers for Cloud Functions, waiting for function deployment
        to complete before extracting the trigger URL.
        
        Args:
            function: Function instance to create trigger for
            trigger_type: Type of trigger to create (only HTTP supported)
            
        Returns:
            Created trigger instance with URL and configuration
            
        Raises:
            RuntimeError: If trigger type is not supported
        """
        from sebs.gcp.triggers import HTTPTrigger

        if trigger_type == Trigger.TriggerType.HTTP:

            location = self.config.region
            project_name = self.config.project_name
            full_func_name = GCP.get_full_function_name(project_name, location, function.name)
            self.logging.info(f"Function {function.name} - waiting for deployment...")
            our_function_req = (
                self.function_client.projects().locations().functions().get(name=full_func_name)
            )
            deployed = False
            while not deployed:
                status_res = our_function_req.execute()
                if status_res["status"] == "ACTIVE":
                    deployed = True
                else:
                    time.sleep(3)
            self.logging.info(f"Function {function.name} - deployed!")
            invoke_url = status_res["httpsTrigger"]["url"]

            trigger = HTTPTrigger(invoke_url)
        else:
            raise RuntimeError("Not supported!")

        trigger.logging_handlers = self.logging_handlers
        function.add_trigger(trigger)
        self.cache_client.update_function(function)
        return trigger

    def cached_function(self, function: Function) -> None:
        """Configure a cached function instance for use.
        
        Sets up library triggers for functions loaded from cache, ensuring
        they have the proper deployment client and logging configuration.
        
        Args:
            function: Cached function instance to configure
        """

        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import LibraryTrigger

        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            gcp_trigger = cast(LibraryTrigger, trigger)
            gcp_trigger.logging_handlers = self.logging_handlers
            gcp_trigger.deployment_client = self

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ) -> None:
        """Update an existing Cloud Function with new code and configuration.
        
        Uploads new code package to Cloud Storage and patches the existing function
        with updated runtime, memory, timeout, and environment variables. Waits
        for deployment to complete before returning.
        
        Args:
            function: Existing function instance to update
            code_package: New benchmark package with updated code
            container_deployment: Whether to use container deployment (unsupported)
            container_uri: Container image URI (unused)
            
        Raises:
            NotImplementedError: If container_deployment is True
            RuntimeError: If function update fails after maximum retries
        """

        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in GCP")

        function = cast(GCPFunction, function)
        language_runtime = code_package.language_version

        function_cfg = FunctionConfig.from_benchmark(code_package)
        architecture = function_cfg.architecture.value
        code_package_name = os.path.basename(code_package.code_location)
        storage = cast(GCPStorage, self._system_resources.get_storage())
        code_package_name = f"{architecture}-{code_package_name}"

        bucket = function.code_bucket(code_package.benchmark, storage)
        storage.upload(bucket, code_package.code_location, code_package_name)

        envs = self._generate_function_envs(code_package)

        self.logging.info(f"Uploaded new code package to {bucket}/{code_package_name}")
        full_func_name = GCP.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )
        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(
                name=full_func_name,
                body={
                    "name": full_func_name,
                    "entryPoint": "handler",
                    "runtime": code_package.language_name + language_runtime.replace(".", ""),
                    "availableMemoryMb": function.config.memory,
                    "timeout": str(function.config.timeout) + "s",
                    "httpsTrigger": {},
                    "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
                    "environmentVariables": envs,
                },
            )
        )
        res = req.execute()
        versionId = res["metadata"]["versionId"]
        retries = 0
        last_version = -1
        while retries < 100:
            is_deployed, last_version = self.is_deployed(function.name, versionId)
            if not is_deployed:
                time.sleep(5)
                retries += 1
            else:
                break
            if retries > 0 and retries % 10 == 0:
                self.logging.info(f"Waiting for function deployment, {retries} retries.")
        if retries == 100:
            raise RuntimeError(
                "Failed to publish new function code after 10 attempts. "
                f"Version {versionId} has not been published, last version {last_version}."
            )
        self.logging.info("Published new function code and configuration.")

    def _update_envs(self, full_function_name: str, envs: Dict) -> Dict:
        """Merge new environment variables with existing function environment.
        
        Retrieves current function environment variables and merges them with
        new variables, with new variables taking precedence on conflicts.
        
        Args:
            full_function_name: Fully qualified function name
            envs: New environment variables to add/update
            
        Returns:
            Merged environment variables dictionary
        """

        get_req = (
            self.function_client.projects().locations().functions().get(name=full_function_name)
        )
        response = get_req.execute()

        # preserve old variables while adding new ones.
        # but for conflict, we select the new one
        if "environmentVariables" in response:
            envs = {**response["environmentVariables"], **envs}

        return envs

    def _generate_function_envs(self, code_package: Benchmark) -> Dict:
        """Generate environment variables for function based on benchmark requirements.
        
        Creates environment variables needed by the benchmark, such as NoSQL
        database connection information.
        
        Args:
            code_package: Benchmark package with module requirements
            
        Returns:
            Dictionary of environment variables for the function
        """

        envs = {}
        if code_package.uses_nosql:

            db = (
                cast(GCPSystemResources, self._system_resources)
                .get_nosql_storage()
                .benchmark_database(code_package.benchmark)
            )
            envs["NOSQL_STORAGE_DATABASE"] = db

        return envs

    def update_function_configuration(
        self, function: Function, code_package: Benchmark, env_variables: Dict = {}
    ) -> int:
        """Update function configuration including memory, timeout, and environment.
        
        Updates the Cloud Function's memory allocation, timeout, and environment
        variables without changing the code. Waits for deployment to complete.
        
        Args:
            function: Function instance to update
            code_package: Benchmark package with configuration requirements
            env_variables: Additional environment variables to set
            
        Returns:
            Version ID of the updated function
            
        Raises:
            RuntimeError: If configuration update fails after maximum retries
        """

        assert code_package.has_input_processed

        function = cast(GCPFunction, function)
        full_func_name = GCP.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        envs = self._generate_function_envs(code_package)
        envs = {**envs, **env_variables}
        # GCP might overwrite existing variables
        # If we modify them, we need to first read existing ones and append.
        if len(envs) > 0:
            envs = self._update_envs(full_func_name, envs)

        if len(envs) > 0:

            req = (
                self.function_client.projects()
                .locations()
                .functions()
                .patch(
                    name=full_func_name,
                    updateMask="availableMemoryMb,timeout,environmentVariables",
                    body={
                        "availableMemoryMb": function.config.memory,
                        "timeout": str(function.config.timeout) + "s",
                        "environmentVariables": envs,
                    },
                )
            )

        else:

            req = (
                self.function_client.projects()
                .locations()
                .functions()
                .patch(
                    name=full_func_name,
                    updateMask="availableMemoryMb,timeout",
                    body={
                        "availableMemoryMb": function.config.memory,
                        "timeout": str(function.config.timeout) + "s",
                    },
                )
            )

        res = req.execute()
        versionId = res["metadata"]["versionId"]
        retries = 0
        last_version = -1
        while retries < 100:
            is_deployed, last_version = self.is_deployed(function.name, versionId)
            if not is_deployed:
                time.sleep(5)
                retries += 1
            else:
                break
            if retries > 0 and retries % 10 == 0:
                self.logging.info(f"Waiting for function deployment, {retries} retries.")
        if retries == 100:
            raise RuntimeError(
                "Failed to publish new function code after 10 attempts. "
                f"Version {versionId} has not been published, last version {last_version}."
            )
        self.logging.info("Published new function configuration.")

        return versionId

    @staticmethod
    def get_full_function_name(project_name: str, location: str, func_name: str) -> str:
        """Generate the fully qualified function name for GCP API calls.
        
        Args:
            project_name: GCP project ID
            location: GCP region/location
            func_name: Function name
            
        Returns:
            Fully qualified function name in GCP format
        """
        return f"projects/{project_name}/locations/{location}/functions/{func_name}"

    def prepare_experiment(self, benchmark: str) -> str:
        """Prepare storage resources for benchmark experiment.
        
        Creates a dedicated storage bucket for experiment logs and outputs.
        
        Args:
            benchmark: Name of the benchmark being prepared
            
        Returns:
            Name of the created logs storage bucket
        """
        logs_bucket = self._system_resources.get_storage().add_output_bucket(
            benchmark, suffix="logs"
        )
        return logs_bucket

    def shutdown(self) -> None:
        """Shutdown the GCP system and clean up resources.
        
        Performs cleanup of system resources and calls parent shutdown method.
        """
        cast(GCPSystemResources, self._system_resources).shutdown()
        super().shutdown()

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, requests: Dict, metrics: Dict
    ) -> None:
        """Download execution metrics and logs from GCP monitoring services.
        
        Retrieves function execution times from Cloud Logging and performance
        metrics from Cloud Monitoring. Processes logs to extract execution times
        and collects metrics like memory usage and network egress.
        
        Args:
            function_name: Name of the function to collect metrics for
            start_time: Start timestamp for metric collection (Unix timestamp)
            end_time: End timestamp for metric collection (Unix timestamp)
            requests: Dictionary of requests keyed by execution ID
            metrics: Dictionary to populate with collected metrics
        """

        from google.api_core import exceptions
        from time import sleep

        def wrapper(gen):
            while True:
                try:
                    yield next(gen)
                except StopIteration:
                    break
                except exceptions.ResourceExhausted:
                    self.logging.info("Google Cloud resources exhausted, sleeping 30s")
                    sleep(30)

        """
            Use GCP's logging system to find execution time of each function invocation.

            There shouldn't be problem of waiting for complete results,
            since logs appear very quickly here.
        """
        import google.cloud.logging as gcp_logging

        logging_client = gcp_logging.Client()
        logger = logging_client.logger("cloudfunctions.googleapis.com%2Fcloud-functions")

        """
            GCP accepts only single date format: 'YYYY-MM-DDTHH:MM:SSZ'.
            Thus, we first convert timestamp to UTC timezone.
            Then, we generate correct format.

            Add 1 second to end time to ensure that removing
            milliseconds doesn't affect query.
        """
        timestamps = []
        for timestamp in [start_time, end_time + 1]:
            utc_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            timestamps.append(utc_date.strftime("%Y-%m-%dT%H:%M:%SZ"))

        invocations = logger.list_entries(
            filter_=(
                f'resource.labels.function_name = "{function_name}" '
                f'timestamp >= "{timestamps[0]}" '
                f'timestamp <= "{timestamps[1]}"'
            ),
            page_size=1000,
        )
        invocations_processed = 0
        if hasattr(invocations, "pages"):
            pages = list(wrapper(invocations.pages))
        else:
            pages = [list(wrapper(invocations))]
        entries = 0
        for page in pages:  # invocations.pages:
            for invoc in page:
                entries += 1
                if "execution took" in invoc.payload:
                    execution_id = invoc.labels["execution_id"]
                    # might happen that we get invocation from another experiment
                    if execution_id not in requests:
                        continue
                    # find number of miliseconds
                    regex_result = re.search(r"\d+ ms", invoc.payload)
                    assert regex_result
                    exec_time = regex_result.group().split()[0]
                    # convert into microseconds
                    requests[execution_id].provider_times.execution = int(exec_time) * 1000
                    invocations_processed += 1
        self.logging.info(
            f"GCP: Received {entries} entries, found time metrics for {invocations_processed} "
            f"out of {len(requests.keys())} invocations."
        )

        """
            Use metrics to find estimated values for maximum memory used, active instances
            and network traffic.
            https://cloud.google.com/monitoring/api/metrics_gcp#gcp-cloudfunctions
        """

        # Set expected metrics here
        available_metrics = ["execution_times", "user_memory_bytes", "network_egress"]

        client = monitoring_v3.MetricServiceClient()
        project_name = client.common_project_path(self.config.project_name)

        end_time_nanos, end_time_seconds = math.modf(end_time)
        start_time_nanos, start_time_seconds = math.modf(start_time)

        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(end_time_seconds) + 60},
                "start_time": {"seconds": int(start_time_seconds)},
            }
        )

        for metric in available_metrics:

            metrics[metric] = []

            list_request = monitoring_v3.ListTimeSeriesRequest(
                name=project_name,
                filter='metric.type = "cloudfunctions.googleapis.com/function/{}"'.format(metric),
                interval=interval,
            )

            results = client.list_time_series(list_request)
            for result in results:
                if result.resource.labels.get("function_name") == function_name:
                    for point in result.points:
                        metrics[metric] += [
                            {
                                "mean_value": point.value.distribution_value.mean,
                                "executions_count": point.value.distribution_value.count,
                            }
                        ]

    def _enforce_cold_start(self, function: Function, code_package: Benchmark) -> int:
        """Force a cold start by updating function configuration.
        
        Triggers a cold start by updating the function's environment variables
        with a unique counter value, forcing GCP to create a new instance.
        
        Args:
            function: Function instance to enforce cold start on
            code_package: Benchmark package for configuration
            
        Returns:
            Version ID of the updated function
        """

        self.cold_start_counter += 1
        new_version = self.update_function_configuration(
            function, code_package, {"cold_start": str(self.cold_start_counter)}
        )

        return new_version

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark) -> None:
        """Enforce cold starts for multiple functions simultaneously.
        
        Updates all provided functions to force cold starts and waits for
        all deployments to complete before returning.
        
        Args:
            functions: List of functions to enforce cold starts on
            code_package: Benchmark package for configuration
        """

        new_versions = []
        for func in functions:
            new_versions.append((self._enforce_cold_start(func, code_package), func))
            self.cold_start_counter -= 1

        # verify deployment
        undeployed_functions = []
        deployment_done = False
        while not deployment_done:
            for versionId, func in new_versions:
                is_deployed, last_version = self.is_deployed(func.name, versionId)
                if not is_deployed:
                    undeployed_functions.append((versionId, func))
            deployed = len(new_versions) - len(undeployed_functions)
            self.logging.info(f"Redeployed {deployed} out of {len(new_versions)}")
            if deployed == len(new_versions):
                deployment_done = True
                break
            time.sleep(5)
            new_versions = undeployed_functions
            undeployed_functions = []

        self.cold_start_counter += 1

    def get_functions(self, code_package: Benchmark, function_names: List[str]) -> List["Function"]:
        """Retrieve multiple function instances and ensure they are deployed.
        
        Gets function instances for the provided names and waits for all
        functions to be in ACTIVE deployment state.
        
        Args:
            code_package: Benchmark package for function creation
            function_names: List of function names to retrieve
            
        Returns:
            List of deployed function instances
        """

        functions: List["Function"] = []
        undeployed_functions_before = []
        for func_name in function_names:
            func = self.get_function(code_package, func_name)
            functions.append(func)
            undeployed_functions_before.append(func)

        # verify deployment
        undeployed_functions = []
        deployment_done = False
        while not deployment_done:
            for func in undeployed_functions_before:
                is_deployed, last_version = self.is_deployed(func.name)
                if not is_deployed:
                    undeployed_functions.append(func)
            deployed = len(undeployed_functions_before) - len(undeployed_functions)
            self.logging.info(f"Deployed {deployed} out of {len(undeployed_functions_before)}")
            if deployed == len(undeployed_functions_before):
                deployment_done = True
                break
            time.sleep(5)
            undeployed_functions_before = undeployed_functions
            undeployed_functions = []
            self.logging.info(f"Waiting on {undeployed_functions_before}")

        return functions

    def is_deployed(self, func_name: str, versionId: int = -1) -> Tuple[bool, int]:
        """Check if a function is deployed and optionally verify version.
        
        Args:
            func_name: Name of the function to check
            versionId: Optional specific version ID to verify (-1 to check any)
            
        Returns:
            Tuple of (is_deployed, current_version_id)
        """
        name = GCP.get_full_function_name(self.config.project_name, self.config.region, func_name)
        function_client = self.get_function_client()
        status_req = function_client.projects().locations().functions().get(name=name)
        status_res = status_req.execute()
        if versionId == -1:
            return (status_res["status"] == "ACTIVE", status_res["versionId"])
        else:
            return (status_res["versionId"] == versionId, status_res["versionId"])

    def deployment_version(self, func: Function) -> int:
        """Get the current deployment version ID of a function.
        
        Args:
            func: Function instance to check
            
        Returns:
            Current version ID of the function
        """
        name = GCP.get_full_function_name(self.config.project_name, self.config.region, func.name)
        function_client = self.get_function_client()
        status_req = function_client.projects().locations().functions().get(name=name)
        status_res = status_req.execute()
        return int(status_res["versionId"])

    @staticmethod
    def helper_zip(base_directory: str, path: str, archive: zipfile.ZipFile) -> None:
        """Recursively add files and directories to a zip archive.
        
        Helper method for recursive_zip that handles directory traversal
        and adds files with relative paths to the archive.
        
        Args:
            base_directory: Base directory path for relative path calculation
            path: Current path being processed (file or directory)
            archive: ZipFile object to add files to
        """
        paths = os.listdir(path)
        for p in paths:
            directory = os.path.join(path, p)
            if os.path.isdir(directory):
                GCP.helper_zip(base_directory, directory, archive)
            else:
                if directory != archive.filename:  # prevent form including itself
                    archive.write(directory, os.path.relpath(directory, base_directory))

    @staticmethod
    def recursive_zip(directory: str, archname: str) -> bool:
        """Create a zip archive of a directory with relative paths.
        
        Creates a compressed zip archive of the specified directory, preserving
        the relative directory structure. Uses maximum compression level.
        
        Args:
            directory: Absolute path to the directory to be zipped
            archname: Path where the zip file should be created
            
        Returns:
            True if archiving was successful
        """
        archive = zipfile.ZipFile(archname, "w", zipfile.ZIP_DEFLATED, compresslevel=9)
        if os.path.isdir(directory):
            GCP.helper_zip(directory, directory, archive)
        else:
            # if the passed directory is actually a file we just add the file to the zip archive
            _, name = os.path.split(directory)
            archive.write(directory, name)
        archive.close()
        return True

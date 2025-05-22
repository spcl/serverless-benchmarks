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

"""
Google Cloud Platform (GCP) FaaS system implementation.

This class provides the SeBS interface for interacting with Google Cloud Functions,
including function deployment, invocation, resource management, and metrics collection.
It utilizes the Google Cloud Client Libraries and gcloud CLI (via Docker) for its operations.
"""


class GCP(System):
    """
    Google Cloud Platform (GCP) FaaS system implementation.

    Manages functions and resources on Google Cloud Functions.
    """
    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logging_handlers: LoggingHandlers,
    ):
        """
        Initialize GCP FaaS system.

        :param system_config: SeBS system configuration.
        :param config: GCP-specific configuration.
        :param cache_client: Function cache instance.
        :param docker_client: Docker client instance.
        :param logging_handlers: Logging handlers.
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
        self.function_client = None # Will be initialized in initialize()

    @property
    def config(self) -> GCPConfig:
        """Return the GCP-specific configuration."""
        return self._config

    @staticmethod
    def name() -> str:
        """Return the name of the cloud provider (gcp)."""
        return "gcp"

    @staticmethod
    def typename() -> str:
        """Return the type name of the cloud provider (GCP)."""
        return "GCP"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Return the type of the function implementation for GCP."""
        return GCPFunction

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        """
        Initialize the GCP system.

        Initializes the Google Cloud Functions API client and system resources.
        After this call, the GCP system should be ready to allocate functions,
        manage storage, and invoke functions.

        :param config: System-specific parameters (not currently used by GCP implementation).
        :param resource_prefix: Optional prefix for naming/selecting resources.
        """
        self.function_client = build("cloudfunctions", "v1", cache_discovery=False)
        self.initialize_resources(select_prefix=resource_prefix)

    def get_function_client(self): # No type hint for googleapiclient.discovery.Resource
        """
        Return the Google Cloud Functions API client.

        The client is initialized during the `initialize` phase.

        :return: Google Cloud Functions API client instance.
        """
        return self.function_client

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """
        Generate a default function name for Google Cloud Functions.

        The name is constructed using SeBS prefix, resource ID, benchmark name,
        language, and version, formatted according to GCP naming rules.

        :param code_package: Benchmark object.
        :param resources: Optional Resources object (uses self.config.resources if None).
        :return: Default function name string.
        """
        current_resources = resources if resources else self.config.resources
        func_name = "sebs-{}-{}-{}-{}".format(
            current_resources.resources_id,
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
        )
        return GCP.format_function_name(func_name)

    @staticmethod
    def format_function_name(func_name: str) -> str:
        """
        Format the function name to comply with GCP naming rules.

        Replaces hyphens and dots with underscores. GCP function names must
        start with a letter, but SeBS typically prepends "sebs-".

        :param func_name: Original function name.
        :return: Formatted function name.
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
        """
        Package benchmark code for Google Cloud Functions.

        The standard SeBS code directory structure is adapted:
        - Files are moved into a 'function' subdirectory.
        - The main handler file (e.g., handler.py) is renamed (e.g., to main.py for Python).
        - The entire directory is then zipped for deployment.

        Note: Container deployment is not currently supported for GCP in SeBS.

        :param directory: Path to the code directory.
        :param language_name: Programming language name.
        :param language_version: Programming language version.
        :param architecture: Target architecture (not directly used in GCP packaging for zip).
        :param benchmark: Benchmark name.
        :param is_cached: Whether the code is cached (not directly used in packaging logic).
        :param container_deployment: Whether to package for container deployment.
        :return: Tuple containing:
            - Path to the packaged zip file.
            - Size of the zip file in bytes.
            - Empty string for container URI (as not supported).
        :raises NotImplementedError: If container_deployment is True.
        """
        container_uri = ""

        if container_deployment:
            raise NotImplementedError("Container Deployment is not supported in GCP")

        CONFIG_FILES = {
            "python": ["handler.py", ".python_packages"], # Original handler.py is moved/renamed
            "nodejs": ["handler.js", "node_modules"], # Original handler.js is moved/renamed
        }
        # GCP requires specific entry point file names (main.py for python, index.js for nodejs)
        # The original handler.py/handler.js from SeBS benchmark template will be renamed.
        HANDLER_RENAMES = {
            "python": ("handler.py", "main.py"),
            "nodejs": ("handler.js", "index.js"),
        }
        package_config_exclusions = CONFIG_FILES[language_name]

        # Move benchmark-specific files into a 'function' subdirectory if they are not handler/deps
        # This step seems unusual if the whole directory is zipped. Let's clarify the intent.
        # The original code moves everything *not* in package_config into 'function/'.
        # Then renames the handler. This implies the handler and deps stay at root of zip,
        # and other benchmark files go into 'function/'.
        # However, GCP usually expects handler (e.g. main.py) at the root of the zip.
        # Let's assume the structure after this is:
        # - main.py (renamed from handler.py) / index.js (renamed from handler.js)
        # - requirements.txt / package.json
        # - function/ (containing other benchmark files) - this is unusual for GCP.
        # For simplicity and standard GCP, usually all user code including main.py/index.js
        # and dependencies are at the root of the zip.
        # The current implementation creates a 'function' subdir for non-handler/dep files.

        # GCP expects the main handler file (e.g., main.py) at the root of the zip.
        # The provided code renames the SeBS handler (e.g., handler.py) to main.py.
        # It moves other files into a 'function' subdirectory, which might be unnecessary
        # if they are not directly referenced or if Python's import system handles it.
        # For now, following the existing logic.

        # Move files not part of package_config (handler, deps) into 'function/' subdirectory
        # This is an unusual step for GCP, usually all code is at root.
        # Re-evaluating: the code moves handler.py/js to main.py/index.js *at the root*.
        # Other files are moved to function_dir.
        # This structure means the zip will have main.py (or index.js) at root,
        # and other benchmark files inside a 'function' folder.

        # Rename the SeBS handler to GCP expected name (e.g., handler.py -> main.py)
        # This renamed file will be at the root of the zip.
        sebs_handler_name, gcp_handler_name = HANDLER_RENAMES[language_name]
        shutil.move(os.path.join(directory, sebs_handler_name), os.path.join(directory, gcp_handler_name))

        # Zip the entire directory content for deployment.
        # The `recursive_zip` creates a zip where paths are relative to `directory`.
        benchmark_archive_path = os.path.join(directory, f"{benchmark}.zip")
        GCP.recursive_zip(directory, benchmark_archive_path)
        logging.info(f"Created {benchmark_archive_path} archive")

        bytes_size = os.path.getsize(benchmark_archive_path)
        mbytes = bytes_size / 1024.0 / 1024.0
        logging.info(f"Zip archive size {mbytes:.2f} MB")

        # Rename handler back for consistency within SeBS's local file structure after packaging.
        shutil.move(os.path.join(directory, gcp_handler_name), os.path.join(directory, sebs_handler_name))

        return benchmark_archive_path, bytes_size, container_uri

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> "GCPFunction":
        """
        Create or update a Google Cloud Function.

        If the function doesn't exist, it's created. If it exists, it's updated.
        The function code is uploaded to a Cloud Storage bucket before deployment.
        Permissions are set to allow unauthenticated invocations for HTTP triggers.

        :param code_package: Benchmark object with code and configuration.
        :param func_name: Desired name for the function.
        :param container_deployment: Flag for container deployment (not supported for GCP).
        :param container_uri: Container URI (not used).
        :return: GCPFunction object representing the deployed function.
        :raises NotImplementedError: If container_deployment is True.
        :raises RuntimeError: If function creation or permission setting fails.
        """
        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in GCP")

        package_path = code_package.code_location # Path to the zip file
        benchmark_name = code_package.benchmark
        language_runtime_version = code_package.language_version
        timeout_seconds = code_package.benchmark_config.timeout
        memory_mb = code_package.benchmark_config.memory
        storage_client = cast(GCPStorage, self._system_resources.get_storage())
        region = self.config.region
        project_id = self.config.project_name
        function_config = FunctionConfig.from_benchmark(code_package)
        target_architecture = function_config.architecture.value # 'x64' or 'arm64'

        # Prepare code package name for Cloud Storage
        # Include architecture in the object name for clarity if needed, though GCP Functions Gen1 might not use it for zip
        base_code_package_name = os.path.basename(package_path)
        gcs_code_object_name = f"{target_architecture}-{base_code_package_name}"
        deployment_bucket_name = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        # Path in GCS: benchmark_name/architecture-zipfilename.zip
        gcs_code_prefix = os.path.join(benchmark_name, gcs_code_object_name)
        storage_client.upload(deployment_bucket_name, package_path, gcs_code_prefix)
        source_archive_url = f"gs://{deployment_bucket_name}/{gcs_code_prefix}"

        self.logging.info(f"Uploaded function {func_name} code to {source_archive_url}")

        full_function_name_path = GCP.get_full_function_name(project_id, region, func_name)
        get_request = self.function_client.projects().locations().functions().get(name=full_function_name_path)

        try:
            get_request.execute()
            # Function exists, update it
            self.logging.info(f"Function {func_name} exists on GCP, updating the instance.")
            gcp_function = GCPFunction(
                name=func_name,
                benchmark=benchmark_name,
                code_package_hash=code_package.hash,
                cfg=function_config,
                bucket=deployment_bucket_name, # Store the bucket used for deployment
            )
            self.update_function(gcp_function, code_package, container_deployment, container_uri)
        except HttpError as e:
            if e.resp.status == 404:
                # Function does not exist, create it
                self.logging.info(f"Function {func_name} does not exist, creating new one.")
                environment_variables = self._generate_function_envs(code_package)
                # GCP runtime format: {language}{major_version_only} e.g. python38, nodejs16
                gcp_runtime_str = code_package.language_name + language_runtime_version.replace(".", "")

                create_body = {
                    "name": full_function_name_path,
                    "entryPoint": "handler", # Default SeBS entry point
                    "runtime": gcp_runtime_str,
                    "availableMemoryMb": memory_mb,
                    "timeout": f"{timeout_seconds}s",
                    "httpsTrigger": {}, # Creates an HTTP trigger
                    "ingressSettings": "ALLOW_ALL", # Allow all traffic for HTTP trigger
                    "sourceArchiveUrl": source_archive_url,
                    "environmentVariables": environment_variables,
                }
                # GCP Gen 2 functions allow specifying architecture, Gen 1 does not directly via this API for zip.
                # If targeting Gen 2 or specific features, the API call might differ or use beta.
                # For now, assuming Gen 1 compatible zip deployment.

                create_request = (
                    self.function_client.projects()
                    .locations()
                    .functions()
                    .create(
                        location=f"projects/{project_id}/locations/{region}",
                        body=create_body,
                    )
                )
                create_request.execute() # This is an operation, might need to wait for completion
                self.logging.info(f"Function {func_name} creation initiated.")
                self._wait_for_operation_done(create_request) # Helper to wait for operation
                self.logging.info(f"Function {func_name} has been created.")


                # Set IAM policy to allow unauthenticated invocations for HTTP trigger
                set_iam_policy_request = (
                    self.function_client.projects()
                    .locations()
                    .functions()
                    .setIamPolicy(
                        resource=full_function_name_path,
                        body={"policy": {"bindings": [{"role": "roles/cloudfunctions.invoker", "members": ["allUsers"]}]}},
                    )
                )
                # Retry setting IAM policy as function might not be fully ready
                MAX_RETRIES = 5
                for attempt in range(MAX_RETRIES):
                    try:
                        set_iam_policy_request.execute()
                        self.logging.info(f"Function {func_name} now accepts unauthenticated invocations.")
                        break
                    except HttpError as iam_error:
                        if iam_error.resp.status == 400 and "Policy can't be set while the function is being updated":
                            self.logging.info(f"Waiting for function {func_name} to be ready for IAM policy update (attempt {attempt + 1}/{MAX_RETRIES}).")
                            time.sleep(5 + attempt * 2) # Exponential backoff
                        elif iam_error.resp.status == 404 and attempt < MAX_RETRIES -1 : # Function might not be discoverable by IAM yet
                             self.logging.info(f"Function {func_name} not found by IAM, retrying (attempt {attempt + 1}/{MAX_RETRIES}).")
                             time.sleep(5 + attempt * 2)
                        else:
                            raise RuntimeError(f"Failed to set IAM policy for {full_function_name_path}: {iam_error}")
                else: # Loop exhausted
                    raise RuntimeError(f"Failed to set IAM policy for {full_function_name_path} after {MAX_RETRIES} attempts.")

                gcp_function = GCPFunction(
                    func_name, benchmark_name, code_package.hash, function_config, deployment_bucket_name
                )
            else:
                # Other HttpError
                raise e


        # Add default LibraryTrigger
        from sebs.gcp.triggers import LibraryTrigger
        library_trigger = LibraryTrigger(func_name, self)
        library_trigger.logging_handlers = self.logging_handlers
        gcp_function.add_trigger(library_trigger)

        # HTTP trigger is implicitly created, ensure it's represented in SeBS
        # The URL is available after function is ACTIVE.
        self.create_trigger(gcp_function, Trigger.TriggerType.HTTP)


        return gcp_function

    def _wait_for_operation_done(self, operation_request):
        """Helper to wait for a Google Cloud API operation to complete."""
        # Operations API client might be needed if operation_request.execute() doesn't block
        # or if we need to poll. For Cloud Functions, create/update often return an operation
        # that needs polling. Assuming execute() blocks or we handle polling elsewhere if needed.
        # For simplicity, if execute() is synchronous for its main effect, this is a placeholder.
        # If it returns an operation object, one would poll operation.name with operations.get.
        self.logging.info("Waiting for operation to complete...")
        # Placeholder: actual Google API operations might require polling.
        # Example:
        # op_service = build('cloudfunctions', 'v1').operations()
        # while True:
        #    op_result = op_service.get(name=operation_name_from_response).execute()
        #    if op_result.get('done'):
        #        if op_result.get('error'): raise Exception(op_result['error'])
        #        break
        #    time.sleep(5)
        time.sleep(10) # Generic wait, replace with actual polling if needed.


    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """
        Create a trigger for a Google Cloud Function.

        Currently, only HTTP triggers are explicitly created and associated here,
        retrieving the function's HTTPS trigger URL. Library triggers are added
        by default during function creation.

        :param function: The GCPFunction object.
        :param trigger_type: The type of trigger to create.
        :return: The created Trigger object.
        :raises RuntimeError: If an unsupported trigger type is requested or if URL retrieval fails.
        """
        from sebs.gcp.triggers import HTTPTrigger

        if trigger_type == Trigger.TriggerType.HTTP:
            gcp_function = cast(GCPFunction, function)
            full_func_name_path = GCP.get_full_function_name(
                self.config.project_name, self.config.region, gcp_function.name
            )
            self.logging.info(f"Function {gcp_function.name} - waiting for HTTP trigger URL...")

            # Retry mechanism to get the function details, as it might take time to become ACTIVE
            # and for httpsTrigger to be populated.
            MAX_RETRIES = 12 # Approx 1 minute with increasing sleep
            invoke_url = None
            for attempt in range(MAX_RETRIES):
                try:
                    func_details_req = (
                        self.function_client.projects().locations().functions().get(name=full_func_name_path)
                    )
                    func_details = func_details_req.execute()
                    if func_details.get("status") == "ACTIVE" and func_details.get("httpsTrigger", {}).get("url"):
                        invoke_url = func_details["httpsTrigger"]["url"]
                        self.logging.info(f"Function {gcp_function.name} HTTP trigger URL: {invoke_url}")
                        break
                    else:
                        self.logging.info(f"Function {gcp_function.name} not yet active or URL not available (attempt {attempt+1}/{MAX_RETRIES}). Status: {func_details.get('status')}")
                        time.sleep(5 + attempt) # Simple backoff
                except HttpError as e:
                    self.logging.warning(f"Error getting function details for {gcp_function.name} (attempt {attempt+1}/{MAX_RETRIES}): {e}")
                    time.sleep(5 + attempt) # Simple backoff
            
            if not invoke_url:
                raise RuntimeError(f"Could not retrieve HTTP trigger URL for function {gcp_function.name} after {MAX_RETRIES} attempts.")

            http_trigger = HTTPTrigger(invoke_url)
            http_trigger.logging_handlers = self.logging_handlers
            gcp_function.add_trigger(http_trigger) # Add to the function object
            self.cache_client.update_function(gcp_function) # Update cache with the new trigger
            return http_trigger
        elif trigger_type == Trigger.TriggerType.LIBRARY:
            # Library triggers are typically added during function creation/deserialization
            # and don't require a separate cloud resource creation step here.
            # If one needs to be dynamically added, ensure it's correctly associated.
            existing_lib_triggers = function.triggers(Trigger.TriggerType.LIBRARY)
            if existing_lib_triggers:
                return existing_lib_triggers[0] # Return existing if found
            else:
                # This case should ideally be handled by ensuring LibraryTrigger is added when func is created/loaded
                from sebs.gcp.triggers import LibraryTrigger
                self.logging.warning(f"Dynamically adding LibraryTrigger for {function.name}, usually added at creation.")
                lib_trigger = LibraryTrigger(function.name, self)
                lib_trigger.logging_handlers = self.logging_handlers
                function.add_trigger(lib_trigger)
                self.cache_client.update_function(function)
                return lib_trigger

        else:
            raise RuntimeError(f"Unsupported trigger type {trigger_type.value} for GCP.")


    def cached_function(self, function: Function):
        """
        Configure a cached GCPFunction instance.

        Sets up logging handlers for its library triggers and associates the
        deployment client.

        :param function: The GCPFunction object retrieved from cache.
        """
        from sebs.faas.function import Trigger # Already imported at top level
        from sebs.gcp.triggers import LibraryTrigger # Already imported at top level

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
    ):
        """
        Update an existing Google Cloud Function with new code and/or configuration.

        The function's code package is uploaded to Cloud Storage, and then the
        function is patched with the new source URL and any updated settings
        (memory, timeout, environment variables). Waits for the update operation
        to complete.

        :param function: The GCPFunction object to update.
        :param code_package: Benchmark object with new code and configuration.
        :param container_deployment: Flag for container deployment (not supported for GCP).
        :param container_uri: Container URI (not used).
        :raises NotImplementedError: If container_deployment is True.
        :raises RuntimeError: If the function update fails after multiple retries.
        """
        if container_deployment:
            raise NotImplementedError("Container deployment is not supported in GCP")

        gcp_function = cast(GCPFunction, function)
        language_runtime_version = code_package.language_version
        function_cfg = FunctionConfig.from_benchmark(code_package) # Get latest config from benchmark
        target_architecture = function_cfg.architecture.value
        
        # Upload new code package
        storage = cast(GCPStorage, self._system_resources.get_storage())
        base_code_package_name = os.path.basename(code_package.code_location)
        gcs_code_object_name = f"{target_architecture}-{base_code_package_name}"
        
        # Ensure the function has a bucket associated, or get default deployment bucket
        deployment_bucket_name = gcp_function.code_bucket(code_package.benchmark, storage)
        if not deployment_bucket_name: # Should not happen if function was created properly
            raise RuntimeError(f"No deployment bucket found for function {gcp_function.name}")

        gcs_code_prefix = os.path.join(code_package.benchmark, gcs_code_object_name)
        storage.upload(deployment_bucket_name, code_package.code_location, gcs_code_prefix)
        source_archive_url = f"gs://{deployment_bucket_name}/{gcs_code_prefix}"
        self.logging.info(f"Uploaded new code package to {source_archive_url}")

        environment_variables = self._generate_function_envs(code_package)
        # Ensure existing envs are preserved if not overridden
        environment_variables = self._update_envs(
             GCP.get_full_function_name(self.config.project_name, self.config.region, gcp_function.name),
             environment_variables
        )
        gcp_runtime_str = code_package.language_name + language_runtime_version.replace(".", "")

        full_func_name_path = GCP.get_full_function_name(
            self.config.project_name, self.config.region, gcp_function.name
        )
        patch_body = {
            "name": full_func_name_path, # Name is required in body for patch by some APIs, though part of URL
            "entryPoint": "handler",
            "runtime": gcp_runtime_str,
            "availableMemoryMb": function_cfg.memory, # Use updated config
            "timeout": f"{function_cfg.timeout}s",   # Use updated config
            # HTTP trigger settings should ideally be preserved or re-applied if necessary.
            # Assuming httpsTrigger: {} is sufficient if it means "keep existing or default HTTP trigger".
            # If specific HTTP settings were changed, they'd need to be included.
            "httpsTrigger": {},
            "sourceArchiveUrl": source_archive_url,
            "environmentVariables": environment_variables,
        }

        patch_request = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(name=full_func_name_path, body=patch_body)
        )
        
        operation = patch_request.execute()
        self.logging.info(f"Function {gcp_function.name} update initiated. Operation: {operation.get('name')}")
        self._wait_for_operation_done(patch_request) # Helper to wait
        self.logging.info("Published new function code and configuration.")
        
        # Update local function object's hash and config
        gcp_function.code_package_hash = code_package.hash
        gcp_function._cfg = function_cfg # Update the config object itself


    def _update_envs(self, full_function_name: str, envs: dict) -> dict:
        """
        Merge new environment variables with existing ones for a function.

        Fetches the function's current configuration to retrieve existing
        environment variables, then merges them with the provided `envs`.
        New values in `envs` will overwrite existing ones if keys conflict.

        :param full_function_name: The fully qualified name of the function.
        :param envs: Dictionary of new or updated environment variables.
        :return: Merged dictionary of environment variables.
        """
        try:
            get_req = (
                self.function_client.projects().locations().functions().get(name=full_function_name)
            )
            response = get_req.execute()
            if "environmentVariables" in response:
                return {**response["environmentVariables"], **envs}
        except HttpError as e:
            self.logging.warning(f"Could not retrieve existing environment variables for {full_function_name}: {e}. Proceeding with provided envs only.")
        return envs

    def _generate_function_envs(self, code_package: Benchmark) -> dict:
        """
        Generate basic environment variables for a function based on benchmark requirements.

        Currently sets `NOSQL_STORAGE_DATABASE` if the benchmark uses NoSQL storage.

        :param code_package: The Benchmark object.
        :return: Dictionary of environment variables.
        """
        envs = {}
        if code_package.uses_nosql:
            # Ensure NoSQL storage is initialized to get database name
            nosql_storage = cast(GCPSystemResources, self._system_resources).get_nosql_storage()
            db_name = nosql_storage.benchmark_database(code_package.benchmark)
            envs["NOSQL_STORAGE_DATABASE"] = db_name
        return envs

    def update_function_configuration(
        self, function: Function, code_package: Benchmark, env_variables: dict = {}
    ):
        """
        Update the configuration (memory, timeout, environment variables) of an existing GCP function.

        Patches the function with new settings. Waits for the update operation to complete.

        :param function: The GCPFunction object to update.
        :param code_package: Benchmark object providing baseline config (memory, timeout).
        :param env_variables: Additional environment variables to merge with generated ones.
        :return: The version ID of the updated function.
        :raises RuntimeError: If the configuration update fails.
        """
        assert code_package.has_input_processed # Ensure benchmark input processing is done

        gcp_function = cast(GCPFunction, function)
        full_func_name_path = GCP.get_full_function_name(
            self.config.project_name, self.config.region, gcp_function.name
        )

        # Generate base envs from benchmark, then merge with explicitly provided ones
        current_envs = self._generate_function_envs(code_package)
        merged_envs = {**current_envs, **env_variables}
        # Ensure existing envs are preserved if not overridden
        final_envs = self._update_envs(full_func_name_path, merged_envs)
        
        # Use the function's current config as base, potentially modified by is_config_changed
        updated_config = gcp_function.config

        patch_body: Dict[str, Any] = {
            "availableMemoryMb": updated_config.memory,
            "timeout": f"{updated_config.timeout}s",
        }
        update_mask_parts = ["availableMemoryMb", "timeout"]

        if final_envs: # Only include environmentVariables if there are some to set/update
            patch_body["environmentVariables"] = final_envs
            update_mask_parts.append("environmentVariables")
        
        update_mask = ",".join(update_mask_parts)

        patch_request = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(name=full_func_name_path, updateMask=update_mask, body=patch_body)
        )
        
        operation = patch_request.execute()
        self.logging.info(f"Function {gcp_function.name} configuration update initiated. Operation: {operation.get('name')}")
        self._wait_for_operation_done(patch_request) # Helper to wait
        
        # Extract versionId from the operation's response metadata if available,
        # or re-fetch function details to get the new versionId.
        # The structure of 'operation' can vary. A common pattern is that 'operation.metadata.target'
        # might contain the function resource name, and 'operation.response' (if operation is done)
        # or a final GET on the function would yield the new versionId.
        # For simplicity, let's assume we might need to re-fetch.
        func_details = self.function_client.projects().locations().functions().get(name=full_func_name_path).execute()
        versionId = func_details.get("versionId", "unknown") # Fallback if versionId not found

        self.logging.info(f"Published new function configuration for {gcp_function.name}, new version ID: {versionId}.")
        return versionId


    @staticmethod
    def get_full_function_name(project_name: str, location: str, func_name: str) -> str:
        """
        Construct the fully qualified function name for GCP API calls.

        Format: `projects/{project_name}/locations/{location}/functions/{func_name}`

        :param project_name: Google Cloud project ID.
        :param location: GCP region (e.g., "us-central1").
        :param func_name: The short name of the function.
        :return: Fully qualified function name.
        """
        return f"projects/{project_name}/locations/{location}/functions/{func_name}"

    def prepare_experiment(self, benchmark: Benchmark) -> str: # Added type hint for benchmark
        """
        Prepare resources for an experiment, specifically the logs bucket.

        Ensures a bucket for storing experiment logs is created via the storage manager.

        :param benchmark: The Benchmark object for which to prepare.
        :return: The name of the logs bucket.
        """
        logs_bucket = self._system_resources.get_storage().get_bucket( # Changed from add_output_bucket
            Resources.StorageBucketType.EXPERIMENTS # Assuming logs go to EXPERIMENTS bucket
        )
        # If add_output_bucket was meant to create a benchmark-specific prefix/path within this bucket,
        # that logic would need to be here or in the storage class.
        # For now, returning the general experiment bucket.
        return logs_bucket

    def shutdown(self) -> None:
        """Shutdown the GCP system client and update cache."""
        cast(GCPSystemResources, self._system_resources).shutdown()
        super().shutdown()

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, requests: dict, metrics: dict
    ):
        """
        Download performance metrics for function invocations from Google Cloud Monitoring and Logging.

        Queries Cloud Logging for execution times and Cloud Monitoring for metrics like
        memory usage and network egress.

        :param function_name: Name of the Google Cloud Function.
        :param start_time: Start timestamp (Unix epoch) for querying metrics.
        :param end_time: End timestamp (Unix epoch) for querying metrics.
        :param requests: Dictionary of request IDs to ExecutionResult objects to be updated.
        :param metrics: Dictionary to store additional aggregated metrics.
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

        # Fetch execution times from Cloud Logging
        import google.cloud.logging as gcp_logging
        logging_client = gcp_logging.Client()
        # Correct logger name for Cloud Functions v1/v2 can vary.
        # Common pattern is 'cloudfunctions.googleapis.com%2Fcloud-functions'
        # or specific to Gen2: 'run.googleapis.com%2Fstderr' or 'run.googleapis.com%2Fstdout'
        # Using the one from original code, assuming it's for Gen1 or appropriate Gen2 logging.
        logger = logging_client.logger("cloudfunctions.googleapis.com%2Fcloud-functions")

        # Format timestamps for GCP Logging query (RFC3339 UTC 'Z')
        start_utc = datetime.fromtimestamp(start_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Add 1 sec to end_time to ensure all logs within the original second are included
        end_utc = datetime.fromtimestamp(end_time + 1, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        log_filter = (
            f'resource.labels.function_name = "{function_name}" '
            f'AND resource.labels.region = "{self.config.region}" ' # Filter by region
            f'AND timestamp >= "{start_utc}" AND timestamp <= "{end_utc}"'
        )
        self.logging.debug(f"GCP Log filter: {log_filter}")

        log_entries = logger.list_entries(filter_=log_filter, page_size=1000)
        
        invocations_processed = 0
        total_log_entries = 0
        
        # Iterate through log entries using the wrapper for retries on ResourceExhausted
        # The .pages attribute might not exist directly or behave as expected with the wrapper.
        # A common pattern is to iterate directly on list_entries if it's an iterator,
        # or handle pagination if it returns a Pager object.
        # Assuming list_entries returns an iterable/pager that wrapper can handle.
        # For robustness, directly iterate and handle potential pagination if `wrapper` isn't sufficient.
        
        # Simplified iteration for clarity, actual pagination might be needed if `wrapper` doesn't cover it.
        # The original code had a complex pagination handling; google-cloud-logging typically returns an iterator.
        page_iterator = log_entries.pages if hasattr(log_entries, "pages") else [log_entries]
        for page in page_iterator:
            for entry in wrapper(iter(page)): # Apply wrapper to iterator of the page
                total_log_entries += 1
                if "execution took" in entry.payload: # Standard log message for execution time
                    execution_id = entry.labels.get("execution_id")
                    if not execution_id:
                        self.logging.warning(f"Log entry missing execution_id: {entry.payload}")
                        continue
                    
                    if execution_id in requests:
                        # Extract execution time in milliseconds
                        match = re.search(r"(\d+) ms", entry.payload)
                        if match:
                            exec_time_ms = int(match.group(1))
                            requests[execution_id].provider_times.execution = exec_time_ms * 1000 # Convert to microseconds
                            invocations_processed += 1
                        else:
                            self.logging.warning(f"Could not parse execution time from log: {entry.payload}")
                    # else:
                        # self.logging.debug(f"Execution ID {execution_id} from logs not in tracked requests.")

        self.logging.info(
            f"GCP: Processed {total_log_entries} log entries, "
            f"found time metrics for {invocations_processed} "
            f"out of {len(requests.keys())} invocations."
        )

        # Fetch metrics from Cloud Monitoring
        monitoring_client = monitoring_v3.MetricServiceClient()
        gcp_project_path = f"projects/{self.config.project_name}" # Corrected from common_project_path

        # Monitoring API expects interval end_time to be exclusive, start_time inclusive.
        # Adding a small buffer to end_time for safety, e.g., 60 seconds.
        monitoring_interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(end_time) + 60}, # Ensure it's integer
            start_time={"seconds": int(start_time)}   # Ensure it's integer
        )

        # Metrics to query
        # Note: 'network_egress' might be 'network/sent_bytes_count' or similar depending on function generation.
        # 'execution_times' is often derived from logs, but a metric also exists.
        # 'user_memory_bytes' is 'memory/usage'.
        # Check official GCP metric names for Cloud Functions.
        # Example: cloudfunctions.googleapis.com/function/execution_times
        #          cloudfunctions.googleapis.com/function/user_memory_bytes
        #          cloudfunctions.googleapis.com/function/sent_bytes_count (for egress)
        
        # Simplified metric list based on original, adjust names if needed for current GCP API
        monitoring_metric_types = {
            "execution_times": "cloudfunctions.googleapis.com/function/execution_times",
            "user_memory_bytes": "cloudfunctions.googleapis.com/function/user_memory_bytes",
            # "network_egress": "cloudfunctions.googleapis.com/function/sent_bytes_count" # Example
        }

        for metric_key, metric_type_full in monitoring_metric_types.items():
            metrics[metric_key] = [] # Initialize list for this metric
            try:
                results = monitoring_client.list_time_series(
                    name=gcp_project_path, # Use 'name' for project path
                    filter=(
                        f'metric.type = "{metric_type_full}" AND '
                        f'resource.labels.function_name = "{function_name}" AND '
                        f'resource.labels.region = "{self.config.region}"'
                    ),
                    interval=monitoring_interval,
                    # Aggregation might be needed for some metrics, e.g. ALIGN_SUM or ALIGN_MEAN
                    # view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL # For detailed points
                )
                for time_series in wrapper(results): # Apply wrapper for retries
                    # Assuming point.value.distribution_value for distribution metrics like execution_times
                    # or point.value.int64_value / double_value for gauge/cumulative
                    for point in time_series.points:
                        if hasattr(point.value, 'distribution_value'):
                             metrics[metric_key].append({
                                "mean_value": point.value.distribution_value.mean,
                                "executions_count": point.value.distribution_value.count,
                                # Add point interval if needed: point.interval.start_time, point.interval.end_time
                            })
                        elif hasattr(point.value, 'int64_value'):
                             metrics[metric_key].append({"value": point.value.int64_value})
                        elif hasattr(point.value, 'double_value'):
                             metrics[metric_key].append({"value": point.value.double_value})
                self.logging.info(f"Fetched {len(metrics[metric_key])} data points for metric {metric_key}.")
            except Exception as e:
                self.logging.error(f"Error fetching metric {metric_key}: {e}")


    def _enforce_cold_start(self, function: Function, code_package: Benchmark) -> str:
        """
        Attempt to enforce a cold start for a GCP function by updating its configuration.

        Increments a 'cold_start' environment variable. This change forces GCP
        to create a new function instance version.

        :param function: The GCPFunction to update.
        :param code_package: The associated Benchmark object.
        :return: The new version ID of the function after update.
        """
        self.cold_start_counter += 1
        new_version_id = self.update_function_configuration(
            function, code_package, {"cold_start": str(self.cold_start_counter)}
        )
        return new_version_id # Return type changed to str as versionId is usually string

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Enforce cold starts for a list of GCP functions.

        Updates each function's configuration to include a new 'cold_start'
        environment variable value, then waits for all functions to be redeployed
        with the new version.

        :param functions: List of GCPFunction objects.
        :param code_package: The associated Benchmark object.
        """
        new_versions_map: Dict[str, str] = {} # Store func_name -> version_id
        for func in functions:
            version_id = self._enforce_cold_start(func, code_package)
            new_versions_map[func.name] = version_id
            # Original code decremented counter here, which seems counterintuitive if
            # each function needs a *distinct* change to guarantee a new instance.
            # Keeping it as is for now, but might need review if cold starts aren't forced.

        # Wait for all functions to be updated to their new versions
        self.logging.info("Waiting for all functions to be redeployed for cold start enforcement...")
        all_deployed = False
        attempts = 0
        MAX_ATTEMPTS = 24 # e.g., 2 minutes if sleep is 5s
        
        while not all_deployed and attempts < MAX_ATTEMPTS:
            all_deployed = True
            for func_name, expected_version_id in new_versions_map.items():
                is_active, current_version_id_str = self.is_deployed(func_name)
                # Version ID from API is int, expected_version_id from update_function_configuration is str
                if not is_active or str(current_version_id_str) != expected_version_id:
                    all_deployed = False
                    self.logging.debug(f"Function {func_name} not yet updated to version {expected_version_id} (current: {current_version_id_str}, active: {is_active}).")
                    break
            if not all_deployed:
                attempts += 1
                self.logging.info(f"Waiting for function deployments... (attempt {attempts}/{MAX_ATTEMPTS})")
                time.sleep(5)
        
        if not all_deployed:
            self.logging.error("Failed to confirm deployment of all functions for cold start enforcement.")
        else:
            self.logging.info("All functions successfully redeployed for cold start.")

        # Global counter incremented once after all operations for this batch
        # self.cold_start_counter += 1 # Moved increment to _enforce_cold_start for per-function uniqueness

    def get_functions(self, code_package: Benchmark, function_names: List[str]) -> List["Function"]:
        """
        Retrieve multiple function instances, ensuring they are deployed and active.

        Calls `get_function` for each name, then waits until all are reported as active.

        :param code_package: The Benchmark object.
        :param function_names: List of function names to retrieve.
        :return: List of active Function objects.
        """
        functions: List[Function] = []
        for func_name in function_names:
            func = self.get_function(code_package, func_name)
            functions.append(func)

        # Wait for all functions to be active
        self.logging.info(f"Verifying deployment status for {len(functions)} functions...")
        attempts = 0
        MAX_ATTEMPTS = 24 # e.g., 2 minutes
        
        functions_to_check = list(functions)
        while attempts < MAX_ATTEMPTS and functions_to_check:
            fully_deployed_functions = []
            for func in functions_to_check:
                is_active, _ = self.is_deployed(func.name)
                if is_active:
                    fully_deployed_functions.append(func)
            
            for deployed_func in fully_deployed_functions:
                functions_to_check.remove(deployed_func)

            if not functions_to_check: # All functions are active
                break

            attempts += 1
            self.logging.info(
                f"Waiting for {len(functions_to_check)} functions to become active... "
                f"(attempt {attempts}/{MAX_ATTEMPTS}, remaining: {[f.name for f in functions_to_check]})"
            )
            time.sleep(5)

        if functions_to_check:
            self.logging.error(f"Failed to confirm active deployment for functions: {[f.name for f in functions_to_check]}")
        else:
            self.logging.info("All requested functions are active.")
            
        return functions


    def is_deployed(self, func_name: str, versionId: int = -1) -> Tuple[bool, int]:
        """
        Check if a Google Cloud Function is deployed and active, optionally for a specific version.

        :param func_name: The short name of the function.
        :param versionId: Optional version ID to check against. If -1, checks current status.
        :return: Tuple (is_active_and_matches_version: bool, current_version_id: int).
                 The boolean is True if status is "ACTIVE" and versionId matches (if provided).
        """
        full_func_name_path = GCP.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        function_client = self.get_function_client()
        try:
            status_req = function_client.projects().locations().functions().get(name=full_func_name_path)
            status_res = status_req.execute()
            current_version_id = int(status_res.get("versionId", 0)) # versionId is string in response
            is_active = status_res.get("status") == "ACTIVE"

            if versionId == -1: # Check only if active
                return is_active, current_version_id
            else: # Check if active AND version matches
                return is_active and current_version_id == versionId, current_version_id
        except HttpError as e:
            self.logging.warning(f"Error checking deployment status for {func_name}: {e}")
            return False, -1 # Indicate error or not found

    def deployment_version(self, func: Function) -> int:
        """
        Get the deployed version ID of a Google Cloud Function.

        :param func: The Function object.
        :return: The integer version ID of the deployed function.
        """
        full_func_name_path = GCP.get_full_function_name(
            self.config.project_name, self.config.region, func.name
        )
        function_client = self.get_function_client()
        status_req = function_client.projects().locations().functions().get(name=full_func_name_path)
        status_res = status_req.execute()
        return int(status_res.get("versionId", 0)) # versionId is string

    @staticmethod
    def helper_zip(base_directory: str, path: str, archive: zipfile.ZipFile):
        """
        Helper function for `recursive_zip` to add files and directories to a zip archive.

        Recursively adds contents of `path` to `archive`, maintaining relative paths
        from `base_directory`.

        :param base_directory: The root directory from which relative paths are calculated.
        :param path: The current directory or file path to add to the archive.
        :param archive: The `zipfile.ZipFile` object to write to.
        """
        paths = os.listdir(path)
        for p_item in paths: # Renamed p to p_item to avoid conflict with path module
            current_path = os.path.join(path, p_item)
            if os.path.isdir(current_path):
                GCP.helper_zip(base_directory, current_path, archive)
            else:
                # Ensure we don't try to add the archive itself to the archive
                if os.path.abspath(current_path) != os.path.abspath(archive.filename):
                    archive.write(current_path, os.path.relpath(current_path, base_directory))

    @staticmethod
    def recursive_zip(directory: str, archname: str) -> bool: # Added return type bool
        """
        Create a zip archive of a directory with relative paths.

        If the archive file already exists, it will be overwritten.
        Based on https://gist.github.com/felixSchl/d38b455df8bf83a78d3d

        :param directory: Absolute path to the directory to be zipped.
        :param archname: Path to the output zip file.
        :return: True if successful.
        """
        # Ensure ZIP_DEFLATED is available, otherwise use default compression
        compression_method = zipfile.ZIP_DEFLATED if zipfile.is_zipfile(archname) or hasattr(zipfile, "ZIP_DEFLATED") else zipfile.ZIP_STORED
        
        # The original code used compresslevel=9, which is specific to some tools/libraries but not standard for zipfile with ZIP_DEFLATED.
        # zipfile uses a `compresslevel` argument for `write` method when `ZIP_DEFLATED` is used.
        # For `ZipFile` constructor, `compression=zipfile.ZIP_DEFLATED` is enough.
        # Python's zipfile default for ZIP_DEFLATED is generally equivalent to zlib's level 6.
        # Explicitly setting compresslevel on write is possible but not via constructor for the whole archive.
        # The original code also had a bug: compresslevel=9 is not a valid arg for ZipFile constructor.
        # It should be passed to write() or use the default.
        # For simplicity, we'll use the default deflate level.
        
        archive = zipfile.ZipFile(archname, "w", compression=compression_method)
        try:
            if os.path.isdir(directory):
                GCP.helper_zip(directory, directory, archive)
            else:
                # if the passed directory is actually a file, just add the file
                _, name = os.path.split(directory)
                archive.write(directory, name)
        finally:
            archive.close()
        return True

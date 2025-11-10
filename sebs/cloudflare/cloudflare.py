import os
import shutil
import json
from typing import cast, Dict, List, Optional, Tuple, Type

import docker
import requests

from sebs.cloudflare.config import CloudflareConfig
from sebs.cloudflare.function import CloudflareWorker
from sebs.cloudflare.resources import CloudflareSystemResources
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers
from sebs.faas.function import Function, ExecutionResult, Trigger, FunctionConfig
from sebs.faas.system import System


class Cloudflare(System):
    """
    Cloudflare Workers serverless platform implementation.
    
    Cloudflare Workers run on Cloudflare's edge network, providing
    low-latency serverless execution globally.
    """
    
    _config: CloudflareConfig

    @staticmethod
    def name():
        return "cloudflare"

    @staticmethod
    def typename():
        return "Cloudflare"

    @staticmethod
    def function_type() -> "Type[Function]":
        return CloudflareWorker

    @property
    def config(self) -> CloudflareConfig:
        return self._config

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: CloudflareConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            CloudflareSystemResources(config, cache_client, docker_client, logger_handlers),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self._api_base_url = "https://api.cloudflare.com/client/v4"

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        """
        Initialize the Cloudflare Workers platform.
        
        Args:
            config: Additional configuration parameters
            resource_prefix: Prefix for resource naming
        """
        # Verify credentials are valid
        self._verify_credentials()
        self.initialize_resources(select_prefix=resource_prefix)

    def _verify_credentials(self):
        """Verify that the Cloudflare API credentials are valid."""
        headers = self._get_auth_headers()
        response = requests.get(f"{self._api_base_url}/user/tokens/verify", headers=headers)
        
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to verify Cloudflare credentials: {response.status_code} - {response.text}"
            )
        
        self.logging.info("Cloudflare credentials verified successfully")

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for Cloudflare API requests."""
        if self.config.credentials.api_token:
            return {
                "Authorization": f"Bearer {self.config.credentials.api_token}",
                "Content-Type": "application/json",
            }
        elif self.config.credentials.email and self.config.credentials.api_key:
            return {
                "X-Auth-Email": self.config.credentials.email,
                "X-Auth-Key": self.config.credentials.api_key,
                "Content-Type": "application/json",
            }
        else:
            raise RuntimeError("Invalid Cloudflare credentials configuration")

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
        Package code for Cloudflare Workers deployment.
        
        Cloudflare Workers support JavaScript/TypeScript and use a bundler
        to create a single JavaScript file for deployment.
        
        Args:
            directory: Path to the code directory
            language_name: Programming language name
            language_version: Programming language version
            architecture: Target architecture (not used for Workers)
            benchmark: Benchmark name
            is_cached: Whether the code is cached
            container_deployment: Whether to deploy as container (not supported)
            
        Returns:
            Tuple of (package_path, package_size, container_uri)
        """
        if container_deployment:
            raise NotImplementedError(
                "Container deployment is not supported for Cloudflare Workers"
            )

        # For now, we'll create a simple package structure
        # In a full implementation, you'd use a bundler like esbuild or webpack
        
        CONFIG_FILES = {
            "nodejs": ["handler.js", "package.json", "node_modules"],
            # Python support via Python Workers is limited
            "python": ["handler.py", "requirements.txt"],
        }
        
        if language_name not in CONFIG_FILES:
            raise NotImplementedError(
                f"Language {language_name} is not yet supported for Cloudflare Workers"
            )

        package_config = CONFIG_FILES[language_name]
        
        # Create a worker directory with the necessary files
        worker_dir = os.path.join(directory, "worker")
        os.makedirs(worker_dir, exist_ok=True)
        
        # Copy all files to worker directory
        for file in os.listdir(directory):
            if file not in package_config and file != "worker":
                src = os.path.join(directory, file)
                dst = os.path.join(worker_dir, file)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
        
        # For now, return the main handler file as the package
        handler_file = "handler.js" if language_name == "nodejs" else "handler.py"
        package_path = os.path.join(directory, handler_file)
        
        if not os.path.exists(package_path):
            raise RuntimeError(f"Handler file {handler_file} not found in {directory}")
        
        bytes_size = os.path.getsize(package_path)
        mbytes = bytes_size / 1024.0 / 1024.0
        self.logging.info(f"Worker package size: {mbytes:.2f} MB")

        return (package_path, bytes_size, "")

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> CloudflareWorker:
        """
        Create a new Cloudflare Worker.
        
        If a worker with the same name already exists, it will be updated.
        
        Args:
            code_package: Benchmark containing the function code
            func_name: Name of the worker
            container_deployment: Whether to deploy as container (not supported)
            container_uri: URI of container image (not used)
            
        Returns:
            CloudflareWorker instance
        """
        if container_deployment:
            raise NotImplementedError(
                "Container deployment is not supported for Cloudflare Workers"
            )

        package = code_package.code_location
        benchmark = code_package.benchmark
        language = code_package.language_name
        language_runtime = code_package.language_version
        function_cfg = FunctionConfig.from_benchmark(code_package)
        
        func_name = self.format_function_name(func_name)
        account_id = self.config.credentials.account_id
        
        if not account_id:
            raise RuntimeError("Cloudflare account ID is required to create workers")

        # Check if worker already exists
        existing_worker = self._get_worker(func_name, account_id)
        
        if existing_worker:
            self.logging.info(f"Worker {func_name} already exists, updating it")
            worker = CloudflareWorker(
                func_name,
                code_package.benchmark,
                func_name,  # script_id is the same as name
                code_package.hash,
                language_runtime,
                function_cfg,
                account_id,
            )
            self.update_function(worker, code_package, container_deployment, container_uri)
            worker.updated_code = True
        else:
            self.logging.info(f"Creating new worker {func_name}")
            
            # Read the worker script
            with open(package, 'r') as f:
                script_content = f.read()
            
            # Create the worker
            self._create_or_update_worker(func_name, script_content, account_id)
            
            worker = CloudflareWorker(
                func_name,
                code_package.benchmark,
                func_name,
                code_package.hash,
                language_runtime,
                function_cfg,
                account_id,
            )

        # Add LibraryTrigger and HTTPTrigger
        from sebs.cloudflare.triggers import LibraryTrigger, HTTPTrigger
        
        library_trigger = LibraryTrigger(func_name, self)
        library_trigger.logging_handlers = self.logging_handlers
        worker.add_trigger(library_trigger)
        
        # Cloudflare Workers are automatically accessible via HTTPS
        worker_url = f"https://{func_name}.{account_id}.workers.dev"
        http_trigger = HTTPTrigger(func_name, worker_url)
        http_trigger.logging_handlers = self.logging_handlers
        worker.add_trigger(http_trigger)

        return worker

    def _get_worker(self, worker_name: str, account_id: str) -> Optional[dict]:
        """Get information about an existing worker."""
        headers = self._get_auth_headers()
        url = f"{self._api_base_url}/accounts/{account_id}/workers/scripts/{worker_name}"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json().get("result")
        elif response.status_code == 404:
            return None
        else:
            raise RuntimeError(
                f"Failed to check worker existence: {response.status_code} - {response.text}"
            )

    def _create_or_update_worker(
        self, worker_name: str, script_content: str, account_id: str
    ) -> dict:
        """Create or update a Cloudflare Worker."""
        headers = self._get_auth_headers()
        # Remove Content-Type as we're sending form data
        headers.pop("Content-Type", None)
        
        url = f"{self._api_base_url}/accounts/{account_id}/workers/scripts/{worker_name}"
        
        # Cloudflare Workers API expects the script as form data
        files = {
            'script': ('worker.js', script_content, 'application/javascript'),
        }
        
        response = requests.put(url, headers=headers, files=files)
        
        if response.status_code not in [200, 201]:
            raise RuntimeError(
                f"Failed to create/update worker: {response.status_code} - {response.text}"
            )
        
        return response.json().get("result", {})

    def cached_function(self, function: Function):
        """
        Handle a function retrieved from cache.
        
        Refreshes triggers and logging handlers.
        
        Args:
            function: The cached function
        """
        from sebs.cloudflare.triggers import LibraryTrigger, HTTPTrigger
        
        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
            cast(LibraryTrigger, trigger).deployment_client = self
            
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ):
        """
        Update an existing Cloudflare Worker.
        
        Args:
            function: Existing function instance to update
            code_package: New benchmark containing the function code
            container_deployment: Whether to deploy as container (not supported)
            container_uri: URI of container image (not used)
        """
        if container_deployment:
            raise NotImplementedError(
                "Container deployment is not supported for Cloudflare Workers"
            )

        worker = cast(CloudflareWorker, function)
        package = code_package.code_location
        
        # Read the updated script
        with open(package, 'r') as f:
            script_content = f.read()
        
        # Update the worker
        account_id = worker.account_id or self.config.credentials.account_id
        if not account_id:
            raise RuntimeError("Account ID is required to update worker")
        
        self._create_or_update_worker(worker.name, script_content, account_id)
        self.logging.info(f"Updated worker {worker.name}")
        
        # Update configuration if needed
        self.update_function_configuration(worker, code_package)

    def update_function_configuration(
        self, cached_function: Function, benchmark: Benchmark
    ):
        """
        Update the configuration of a Cloudflare Worker.
        
        Note: Cloudflare Workers have limited configuration options compared
        to traditional FaaS platforms. Memory and timeout are managed by Cloudflare.
        
        Args:
            cached_function: The function to update
            benchmark: The benchmark with new configuration
        """
        # Cloudflare Workers have fixed resource limits:
        # - CPU time: 50ms (free), 50ms-30s (paid)
        # - Memory: 128MB
        # Most configuration is handled via wrangler.toml or API settings
        
        worker = cast(CloudflareWorker, cached_function)
        
        # For environment variables or KV namespaces, we would use the API here
        # For now, we'll just log that configuration update was requested
        self.logging.info(
            f"Configuration update requested for worker {worker.name}. "
            "Note: Cloudflare Workers have limited runtime configuration options."
        )

    def default_function_name(self, code_package: Benchmark, resources=None) -> str:
        """
        Generate a default function name for Cloudflare Workers.
        
        Args:
            code_package: The benchmark package
            resources: Optional resources (not used)
            
        Returns:
            Default function name
        """
        # Cloudflare Worker names must be lowercase and can contain hyphens
        return (
            f"{code_package.benchmark}-{code_package.language_name}-"
            f"{code_package.language_version.replace('.', '')}"
        ).lower()

    @staticmethod
    def format_function_name(name: str) -> str:
        """
        Format a function name to comply with Cloudflare Worker naming rules.
        
        Worker names must:
        - Be lowercase
        - Contain only alphanumeric characters and hyphens
        - Not start or end with a hyphen
        
        Args:
            name: The original name
            
        Returns:
            Formatted name
        """
        # Convert to lowercase and replace invalid characters
        formatted = name.lower().replace('_', '-').replace('.', '-')
        # Remove any characters that aren't alphanumeric or hyphen
        formatted = ''.join(c for c in formatted if c.isalnum() or c == '-')
        # Remove leading/trailing hyphens
        formatted = formatted.strip('-')
        return formatted

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        """
        Enforce cold start for Cloudflare Workers.
        
        Note: Cloudflare Workers don't have a traditional cold start mechanism
        like AWS Lambda. Workers are instantiated on-demand at edge locations.
        We can't force a cold start, but we can update the worker to invalidate caches.
        
        Args:
            functions: List of functions to enforce cold start on
            code_package: The benchmark package
        """
        self.logging.warning(
            "Cloudflare Workers do not support forced cold starts. "
            "Workers are automatically instantiated on-demand at edge locations."
        )

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
        """
        Extract per-invocation metrics from ExecutionResult objects.
        
        The metrics are extracted from the 'measurement' field in the benchmark
        response, which is populated by the Cloudflare Worker handler during execution.
        This approach avoids dependency on Analytics Engine and provides immediate,
        accurate metrics for each invocation.
        
        Args:
            function_name: Name of the worker
            start_time: Start time (Unix timestamp in seconds) - not used
            end_time: End time (Unix timestamp in seconds) - not used
            requests: Dict mapping request_id -> ExecutionResult
            metrics: Dict to store aggregated metrics
        """
        if not requests:
            self.logging.warning("No requests to extract metrics from")
            return
        
        self.logging.info(
            f"Extracting metrics from {len(requests)} invocations "
            f"of worker {function_name}"
        )
        
        # Aggregate statistics from all requests
        total_invocations = len(requests)
        cold_starts = 0
        warm_starts = 0
        cpu_times = []
        wall_times = []
        memory_values = []
        
        for request_id, result in requests.items():
            # Count cold/warm starts
            if result.stats.cold_start:
                cold_starts += 1
            else:
                warm_starts += 1
            
            # Collect CPU times
            if result.provider_times.execution > 0:
                cpu_times.append(result.provider_times.execution)
            
            # Collect wall times (benchmark times)
            if result.times.benchmark > 0:
                wall_times.append(result.times.benchmark)
            
            # Collect memory usage
            if result.stats.memory_used > 0:
                memory_values.append(result.stats.memory_used)
            
            # Set billing info for Cloudflare Workers
            # Cloudflare billing: $0.50 per million requests + 
            # $12.50 per million GB-seconds of CPU time
            if result.provider_times.execution > 0:
                result.billing.memory = 128  # Cloudflare Workers: fixed 128MB
                result.billing.billed_time = result.provider_times.execution  # μs
                
                # GB-seconds calculation: (128MB / 1024MB/GB) * (cpu_time_us / 1000000 us/s)
                cpu_time_seconds = result.provider_times.execution / 1_000_000.0
                gb_seconds = (128.0 / 1024.0) * cpu_time_seconds
                result.billing.gb_seconds = int(gb_seconds * 1_000_000)  # micro GB-seconds
        
        # Calculate statistics
        metrics['cloudflare'] = {
            'total_invocations': total_invocations,
            'cold_starts': cold_starts,
            'warm_starts': warm_starts,
            'data_source': 'response_measurements',
            'note': 'Per-invocation metrics extracted from benchmark response'
        }
        
        if cpu_times:
            metrics['cloudflare']['avg_cpu_time_us'] = sum(cpu_times) // len(cpu_times)
            metrics['cloudflare']['min_cpu_time_us'] = min(cpu_times)
            metrics['cloudflare']['max_cpu_time_us'] = max(cpu_times)
            metrics['cloudflare']['cpu_time_measurements'] = len(cpu_times)
        
        if wall_times:
            metrics['cloudflare']['avg_wall_time_us'] = sum(wall_times) // len(wall_times)
            metrics['cloudflare']['min_wall_time_us'] = min(wall_times)
            metrics['cloudflare']['max_wall_time_us'] = max(wall_times)
            metrics['cloudflare']['wall_time_measurements'] = len(wall_times)
        
        if memory_values:
            metrics['cloudflare']['avg_memory_mb'] = sum(memory_values) / len(memory_values)
            metrics['cloudflare']['min_memory_mb'] = min(memory_values)
            metrics['cloudflare']['max_memory_mb'] = max(memory_values)
            metrics['cloudflare']['memory_measurements'] = len(memory_values)
        
        self.logging.info(
            f"Extracted metrics from {total_invocations} invocations: "
            f"{cold_starts} cold starts, {warm_starts} warm starts"
        )
        
        if cpu_times:
            avg_cpu_ms = sum(cpu_times) / len(cpu_times) / 1000.0
            self.logging.info(f"Average CPU time: {avg_cpu_ms:.2f} ms")
        
        if wall_times:
            avg_wall_ms = sum(wall_times) / len(wall_times) / 1000.0
            self.logging.info(f"Average wall time: {avg_wall_ms:.2f} ms")

    def create_trigger(
        self, function: Function, trigger_type: Trigger.TriggerType
    ) -> Trigger:
        """
        Create a trigger for a Cloudflare Worker.
        
        Args:
            function: The function to create a trigger for
            trigger_type: Type of trigger to create
            
        Returns:
            The created trigger
        """
        from sebs.cloudflare.triggers import LibraryTrigger, HTTPTrigger
        
        worker = cast(CloudflareWorker, function)
        
        if trigger_type == Trigger.TriggerType.LIBRARY:
            trigger = LibraryTrigger(worker.name, self)
            trigger.logging_handlers = self.logging_handlers
            return trigger
        elif trigger_type == Trigger.TriggerType.HTTP:
            account_id = worker.account_id or self.config.credentials.account_id
            worker_url = f"https://{worker.name}.{account_id}.workers.dev"
            trigger = HTTPTrigger(worker.name, worker_url)
            trigger.logging_handlers = self.logging_handlers
            return trigger
        else:
            raise NotImplementedError(
                f"Trigger type {trigger_type} is not supported for Cloudflare Workers"
            )

    def shutdown(self) -> None:
        """
        Shutdown the Cloudflare system.
        
        Saves configuration to cache.
        """
        try:
            self.cache_client.lock()
            self.config.update_cache(self.cache_client)
        finally:
            self.cache_client.unlock()

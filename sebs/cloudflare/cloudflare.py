import os
import uuid
import time
from datetime import datetime
from typing import cast, Dict, List, Optional, Tuple, Type

import docker
import requests

from sebs.cloudflare.config import CloudflareConfig
from sebs.cloudflare.function import CloudflareWorker
from sebs.cloudflare.resources import CloudflareSystemResources
from sebs.cloudflare.workers import CloudflareWorkersDeployment
from sebs.cloudflare.containers import CloudflareContainersDeployment
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers
from sebs.faas.function import Function, ExecutionResult, Trigger, FunctionConfig
from sebs.faas.system import System
from sebs.faas.config import Resources
from sebs.sebs_types import Language


class _CloudflareContainerAdapter:
    """Duck-typed adapter that satisfies benchmark.build()'s container_client contract.

    benchmark.build() calls container_client.build_base_image() when
    container_deployment=True and asserts the client is not None.  Cloudflare
    builds its container images inside package_code (via containers.py), not
    through a registry-backed DockerContainer, so this adapter bridges the gap
    without touching the framework.
    """

    def __init__(self, containers_deployment: CloudflareContainersDeployment):
        self._containers = containers_deployment
        # Populated by build_base_image() so create_function() can find the dir.
        self.last_directory: Optional[str] = None

    def build_base_image(
        self,
        directory: str,
        language,            # sebs.sebs_types.Language enum
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        builder_image: str,
    ) -> Tuple[bool, str, float]:
        """Delegate to containers.package_code; match benchmark.build() contract.

        Returns (rebuilt, image_tag, size_mb) so that:
            _, self._container_uri, self._code_size = container_client.build_base_image(...)
        works correctly in benchmark.build().
        """
        dir_result, size_bytes, image_tag = self._containers.package_code(
            directory,
            language.value,      # Language enum → str
            language_version,
            architecture,
            benchmark,
        )
        self.last_directory = dir_result
        size_mb = size_bytes / 1024.0 / 1024.0
        return (True, image_tag, size_mb)

    def push_to_registry(
        self,
        benchmark: str,
        language_name: str,
        language_version: str,
        architecture: str,
    ) -> str:
        """
        Return a local cache label for the container image.

        Cloudflare container workers do not use a conventional image registry.
        Instead, `wrangler deploy` reads `./Dockerfile` directly from the
        package directory, builds the image, and pushes it to Cloudflare's
        managed registry — all in one step.  SeBS therefore never needs to
        push an image to an external registry before deployment; this method
        exists only to satisfy the `ContainerSystemInterface` contract and to
        provide a stable cache key that `Benchmark` uses to detect whether a
        previously-built image is still valid.

        The returned string is a local image tag of the form
        ``<sanitised-benchmark-name>-<language>-<version>:latest``.  It is
        NOT a pushable URI and is not passed to any registry client.
        """
        image_name = (
            f"{benchmark.replace('.', '-')}-{language_name}-"
            f"{language_version.replace('.', '')}"
        )
        return f"{image_name}:latest"


class Cloudflare(System):
    """
    Cloudflare Workers serverless platform implementation.

    Cloudflare Workers run on Cloudflare's edge network, providing
    low-latency serverless execution globally.
    """

    # Benchmarks supported per (language, container_deployment) combination.
    # Keys are (language_name, container_deployment).
    # A value of None means all benchmarks are supported.
    # Benchmark IDs are matched against the numeric prefix of the benchmark name
    # (e.g. "110" matches "110.dynamic-html").
    SUPPORTED_BENCHMARKS: Dict[Tuple[str, bool], Optional[List[str]]] = {
        ("python", False): ["110", "120", "130", "210", "311", "501", "502", "503"],
        ("nodejs", False): ["110", "120", "130", "311"],
        ("python", True):  None,   # all benchmarks supported
        ("nodejs", True):  ["110", "120", "130", "210", "311"],
    }

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

    def is_benchmark_supported(self, benchmark_name: str, language: str, container_deployment: bool) -> bool:
        """Return True if the benchmark is supported for the given language/deployment type.

        Args:
            benchmark_name: Full benchmark name, e.g. "110.dynamic-html"
            language: Language name, e.g. "python" or "nodejs"
            container_deployment: Whether this is a container deployment

        Returns:
            True if supported, False otherwise
        """
        allowed = self.SUPPORTED_BENCHMARKS.get((language, container_deployment))
        if allowed is None:
            # None means all benchmarks are supported
            return True
        # Match by numeric prefix (the part before the first dot)
        prefix = benchmark_name.split(".")[0]
        return prefix in allowed

    def get_function(self, code_package: Benchmark, func_name: Optional[str] = None) -> Function:
        """Override to validate benchmark support and auto-select cloudflare variant."""
        language = code_package.language_name
        container_deployment = code_package.container_deployment
        benchmark_name = code_package.benchmark
        if not self.is_benchmark_supported(benchmark_name, language, container_deployment):
            deployment_type = "container" if container_deployment else "worker"
            raise RuntimeError(
                f"Benchmark '{benchmark_name}' is not supported for "
                f"{language} {deployment_type} deployments on Cloudflare. "
                f"Supported benchmarks: {self.SUPPORTED_BENCHMARKS.get((language, container_deployment))}"
            )

        # For workers deployments, auto-promote the variant from "default" to
        # "cloudflare" when the benchmark's config.json declares a "cloudflare"
        # variant.  Benchmark.__init__ sets the variant from the experiment config
        # (CLI --language-variant flag), which defaults to "default".  Promoting
        # here ensures copy_code() applies the cloudflare/ source overlay and the
        # cache key reflects the correct variant.
        if (
            code_package.language_variant == "default"
            and code_package.benchmark_config.supports(code_package.language, self.name())
        ):
            code_package.select_variant(self.name())

        return super().get_function(code_package, func_name)

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
        # cached workers.dev subdomain for the account 
        # This is different from the account ID and is required to build
        # public worker URLs like <name>.<subdomain>.workers.dev
        self._workers_dev_subdomain: Optional[str] = None
        
        # Initialize deployment handlers
        self._workers_deployment = CloudflareWorkersDeployment(
            self.logging, sebs_config, docker_client, self.system_resources
        )
        self._containers_deployment = CloudflareContainersDeployment(
            self.logging, sebs_config, docker_client, self.system_resources
        )
        # Adapter so benchmark.build() can call container_client.build_base_image()
        self._container_adapter = _CloudflareContainerAdapter(self._containers_deployment)

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

    def initialize_resources(self, select_prefix: Optional[str] = None):
        """
        Initialize Cloudflare resources.

        Overrides the base class method to handle R2 storage gracefully.
        Cloudflare Workers can operate without R2 storage for many benchmarks.

        Args:
            select_prefix: Optional prefix for resource naming
        """
        deployments = self.find_deployments()

        # Check if we have an existing deployment
        if deployments:
            res_id = deployments[0]
            self.config.resources.resources_id = res_id
            self.logging.info(f"Using existing resource deployment {res_id}")
            return

        # Create new resource ID
        if select_prefix is not None:
            res_id = f"{select_prefix}-{str(uuid.uuid1())[0:8]}"
        else:
            res_id = str(uuid.uuid1())[0:8]

        self.config.resources.resources_id = res_id
        self.logging.info(f"Generating unique resource name {res_id}")

        # Try to create R2 bucket, but don't fail if R2 is not enabled
        try:
            self.system_resources.get_storage().get_bucket(Resources.StorageBucketType.BENCHMARKS)
            self.logging.info("R2 storage initialized successfully")
        except Exception as e:
            self.logging.warning(
                f"R2 storage initialization failed: {e}. "
                f"R2 must be enabled in your Cloudflare dashboard to use storage-dependent benchmarks. "
                f"Continuing without R2 storage - only benchmarks that don't require storage will work."
            )

    @property
    def container_client(self) -> _CloudflareContainerAdapter:
        """Return the Cloudflare-specific container build adapter.

        Overrides System.container_client (which returns None) so that
        benchmark.build() can drive container image builds via
        _CloudflareContainerAdapter.build_base_image() without needing an
        external container registry.
        """
        return self._container_adapter

    def _verify_credentials(self):
        """Verify that the Cloudflare API credentials are valid."""
        # Check if credentials are set
        if not self.config.credentials.api_token and not (self.config.credentials.email and self.config.credentials.api_key):
            raise RuntimeError(
                "Cloudflare API credentials are not set. Please set CLOUDFLARE_API_TOKEN "
                "and CLOUDFLARE_ACCOUNT_ID environment variables."
            )

        if not self.config.credentials.account_id:
            raise RuntimeError(
                "Cloudflare Account ID is not set. Please set CLOUDFLARE_ACCOUNT_ID "
                "environment variable."
            )

        headers = self._get_auth_headers()

        # Log credential type being used (without exposing the actual token)
        if self.config.credentials.api_token:
            token_preview = self.config.credentials.api_token[:8] + "..." if len(self.config.credentials.api_token) > 8 else "***"
            self.logging.info(f"Using API Token authentication (starts with: {token_preview})")
        else:
            self.logging.info(f"Using Email + API Key authentication (email: {self.config.credentials.email})")

        response = requests.get(f"{self._api_base_url}/user/tokens/verify", headers=headers)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to verify Cloudflare credentials: {response.status_code} - {response.text}\n"
                f"Please check that your CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are correct."
            )

        self.logging.info("Cloudflare credentials verified successfully")
    
    def _get_deployment_handler(self, container_deployment: bool):
        """Get the appropriate deployment handler based on deployment type.
        
        Args:
            container_deployment: Whether this is a container deployment
            
        Returns:
            CloudflareWorkersDeployment or CloudflareContainersDeployment
        """
        if container_deployment:
            return self._containers_deployment
        else:
            return self._workers_deployment


    def package_code(
        self,
        directory: str,
        language: Language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:
        """
        Package code for native Cloudflare Workers deployment using Wrangler.

        Called by benchmark.build() via the non-container path.  Container
        builds are driven by _CloudflareContainerAdapter.build_base_image()
        through the container_client property instead.

        Args:
            directory: Path to the code directory
            language: Programming language enum
            language_version: Programming language version
            architecture: Target architecture (not used for Workers)
            benchmark: Benchmark name
            is_cached: Whether the code is cached

        Returns:
            Tuple of (package_path, package_size)
        """
        # Native worker deployment flow — always the cloudflare variant.
        # workers.py returns a 3-tuple (path, size, ""); drop the unused 3rd element.
        pkg_path, pkg_size, _ = self._workers_deployment.package_code(
            directory, language.value, language_version, benchmark, is_cached,
            language_variant="cloudflare",
        )
        return (pkg_path, pkg_size)

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

    def _generate_wrangler_toml(
        self,
        worker_name: str,
        package_dir: str,
        language: str,
        account_id: str,
        benchmark_name: Optional[str] = None,
        code_package: Optional[Benchmark] = None,
        container_deployment: bool = False,
        container_uri: str = "",
    ) -> str:
        """
        Generate wrangler.toml by delegating to the appropriate deployment handler.

        Args:
            worker_name: Name of the worker
            package_dir: Directory containing the worker code
            language: Programming language (nodejs or python)
            account_id: Cloudflare account ID
            benchmark_name: Optional benchmark name for R2 file path prefix
            code_package: Optional benchmark package for nosql configuration
            container_deployment: Whether this is a container deployment
            container_uri: Container image URI/tag

        Returns:
            Path to the generated wrangler.toml file
        """
        language_variant = code_package.language_variant if code_package else "cloudflare"
        handler = self._get_deployment_handler(container_deployment)
        return handler.generate_wrangler_toml(
            worker_name, package_dir, language, account_id,
            benchmark_name, code_package, container_uri, language_variant,
        )

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
            container_deployment: Whether to deploy as container
            container_uri: URI of container image

        Returns:
            CloudflareWorker instance
        """
        # For container builds benchmark.build() goes through container_client.build_base_image(),
        # which does NOT set code_package._code_location.  Fall back to the directory that
        # _CloudflareContainerAdapter stored during its last build_base_image() call.
        package = code_package.code_location
        if package is None and container_deployment:
            package = self._container_adapter.last_directory
        if package is None:
            raise RuntimeError(
                f"Code location is not set for {code_package.benchmark}. "
                "The build step may not have completed successfully."
            )
        benchmark = code_package.benchmark
        language = code_package.language_name
        language_runtime = code_package.language_version
        function_cfg = FunctionConfig.from_benchmark(code_package)

        func_name = self.format_function_name(func_name, container_deployment)
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

            # Create the worker with all package files
            self._create_or_update_worker(func_name, package, account_id, language, benchmark, code_package, container_deployment, container_uri)

            worker = CloudflareWorker(
                func_name,
                code_package.benchmark,
                func_name,
                code_package.hash,
                language_runtime,
                function_cfg,
                account_id,
            )

        # Add HTTPTrigger
        from sebs.cloudflare.triggers import HTTPTrigger

        # Build worker URL using the account's workers.dev subdomain when possible.
        # Falls back to account_id-based host or plain workers.dev with warnings.
        worker_url = self._build_workers_dev_url(func_name, account_id)
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
            try:
                return response.json().get("result")
            except:
                return None
        elif response.status_code == 404:
            return None
        else:
            self.logging.warning(f"Unexpected response checking worker: {response.status_code}")
            return None

    def _create_or_update_worker(
        self, worker_name: str, package_dir: str, account_id: str, language: str, benchmark_name: Optional[str] = None, code_package: Optional[Benchmark] = None, container_deployment: bool = False, container_uri: str = ""
    ) -> dict:
        """Create or update a Cloudflare Worker using Wrangler CLI in container.

        Args:
            worker_name: Name of the worker
            package_dir: Directory containing handler and all benchmark files
            account_id: Cloudflare account ID
            language: Programming language (nodejs or python)
            benchmark_name: Optional benchmark name for R2 file path prefix
            code_package: Optional benchmark package for nosql configuration
            container_deployment: Whether this is a container deployment
            container_uri: Container image URI/tag

        Returns:
            Worker deployment result
        """
        # Set up environment for Wrangler CLI in container
        env = {}

        if self.config.credentials.api_token:
            env['CLOUDFLARE_API_TOKEN'] = self.config.credentials.api_token
        elif self.config.credentials.email and self.config.credentials.api_key:
            env['CLOUDFLARE_EMAIL'] = self.config.credentials.email
            env['CLOUDFLARE_API_KEY'] = self.config.credentials.api_key

        env['CLOUDFLARE_ACCOUNT_ID'] = account_id

        # Get CLI container instance from appropriate deployment handler
        handler = self._get_deployment_handler(container_deployment)
        cli = handler._get_cli()

        # Push the locally-built container image to Cloudflare's registry so that
        # wrangler deploy can reference it directly instead of rebuilding from the
        # Dockerfile. Must happen before generating wrangler.toml so the registry
        # URI is written in from the start.
        if container_deployment and container_uri:
            self.logging.info(f"Pushing container image {container_uri} to Cloudflare registry...")
            container_uri = cli.containers_push(container_uri, env=env)
            self.logging.info(f"Image pushed to: {container_uri}")

        # Generate wrangler.toml for this worker (uses registry URI if available)
        self._generate_wrangler_toml(worker_name, package_dir, language, account_id, benchmark_name, code_package, container_deployment, container_uri)

        # Upload package directory to container
        container_package_path = f"/tmp/workers/{worker_name}"
        self.logging.info(f"Uploading package to container: {container_package_path}")
        cli.upload_package(package_dir, container_package_path)

        # Deploy using Wrangler in container
        self.logging.info(f"Deploying worker {worker_name} using Wrangler in container...")

        language_variant = code_package.language_variant if code_package else "cloudflare"

        try:
            # pywrangler is used for all native Python workers (packages must be
            # synced via pyproject.toml before wrangler uploads the bundle).
            # All other cases — nodejs, containers — use wrangler directly.
            if not container_deployment and language == "python":
                output = cli.pywrangler_deploy(container_package_path, env=env)
            else:
                output = cli.wrangler_deploy(container_package_path, env=env)

            self.logging.info(f"Worker {worker_name} deployed successfully")
            self.logging.debug(f"Wrangler deploy output: {output}")

            # Wait for the worker to become reachable before returning.
            # Container workers expose /health; native workers are probed
            # with a lightweight GET to confirm edge propagation.
            account_id_val = env.get('CLOUDFLARE_ACCOUNT_ID')
            worker_url = self._build_workers_dev_url(worker_name, account_id_val)

            if container_deployment:
                self.logging.info("Waiting for container worker to initialize...")
                self._containers_deployment.wait_for_container_worker_ready(
                    worker_name, worker_url
                )
            else:
                self._wait_for_worker_ready(worker_name, worker_url)
            
            # Keep the container warm for a minimum provisioning window.
            # A flat sleep lets the Durable Object hibernate, which causes the
            # container runtime to reject the next start() call.  Instead we
            # ping /health every few seconds so the DO stays alive.
            if container_deployment:
                warm_seconds = 60
                ping_interval = 5
                account_id = env.get('CLOUDFLARE_ACCOUNT_ID')
                worker_url = self._build_workers_dev_url(worker_name, account_id)
                health_url = f"{worker_url}/health"
                self.logging.info(
                    f"Keeping container warm for {warm_seconds}s "
                    f"(pinging {health_url} every {ping_interval}s)..."
                )
                deadline = time.time() + warm_seconds
                while time.time() < deadline:
                    try:
                        requests.get(health_url, timeout=10)
                    except Exception:
                        pass
                    remaining = deadline - time.time()
                    time.sleep(min(ping_interval, max(0, remaining)))

            return {"success": True, "output": output}

        except RuntimeError as e:
            error_msg = f"Wrangler deployment failed for worker {worker_name}: {str(e)}"
            self.logging.error(error_msg)
            raise RuntimeError(error_msg)

    def _wait_for_worker_ready(
        self, worker_name: str, worker_url: str,
        max_wait_seconds: int = 60, poll_interval: int = 5
    ) -> None:
        """Poll a native worker until it responds, confirming edge propagation."""
        self.logging.info(
            f"Waiting up to {max_wait_seconds}s for worker {worker_name} to become reachable..."
        )
        start = time.time()
        while time.time() - start < max_wait_seconds:
            try:
                resp = requests.get(worker_url, timeout=10)
                if resp.status_code not in (502, 503, 522, 524):
                    self.logging.info(f"Worker {worker_name} is reachable (HTTP {resp.status_code}).")
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(poll_interval)
        self.logging.warning(
            f"Worker {worker_name} not confirmed reachable after {max_wait_seconds}s; "
            "proceeding anyway — invocation retries will handle residual propagation delay."
        )

    def _get_workers_dev_subdomain(self, account_id: str) -> Optional[str]:
        """Fetch the workers.dev subdomain for the given account.

        Cloudflare exposes an endpoint that returns the account-level workers
        subdomain (the readable name used in *.workers.dev), e.g.
        GET /accounts/{account_id}/workers/subdomain

        Returns the subdomain string or None on failure.
        """
        if self._workers_dev_subdomain:
            return self._workers_dev_subdomain

        try:
            headers = self._get_auth_headers()
            url = f"{self._api_base_url}/accounts/{account_id}/workers/subdomain"
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                body = resp.json()
                sub = None
                # result may contain 'subdomain' or nested structure
                if isinstance(body, dict):
                    sub = body.get("result", {}).get("subdomain")

                if sub:
                    self._workers_dev_subdomain = sub
                    return sub
                else:
                    self.logging.warning(
                        "Could not find workers.dev subdomain in API response; "
                        "please enable the workers.dev subdomain in your Cloudflare dashboard."
                    )
                    return None
            else:
                self.logging.warning(
                    f"Failed to fetch workers.dev subdomain: {resp.status_code} - {resp.text}"
                )
                return None
        except Exception as e:
            self.logging.warning(f"Error fetching workers.dev subdomain: {e}")
            return None

    def _build_workers_dev_url(self, worker_name: str, account_id: Optional[str]) -> str:
        """Build a best-effort public URL for a worker.

        Prefer using the account's readable workers.dev subdomain when available
        (e.g. <name>.<subdomain>.workers.dev). If we can't obtain that, fall
        back to using the account_id as a last resort and log a warning.
        """
        if account_id:
            sub = self._get_workers_dev_subdomain(account_id)
            return f"https://{worker_name}.{sub}.workers.dev"
        # Last fallback: plain workers.dev (may not resolve without a subdomain)
        self.logging.warning(
            "No account ID available; using https://{name}.workers.dev which may not be reachable."
        )
        return f"https://{worker_name}.workers.dev"

    def cached_function(self, function: Function):
        """
        Handle a function retrieved from cache.

        Refreshes triggers and logging handlers.

        Args:
            function: The cached function
        """
        from sebs.cloudflare.triggers import HTTPTrigger

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
            container_deployment: Whether to deploy as container
            container_uri: URI of container image
        """
        worker = cast(CloudflareWorker, function)
        package = code_package.code_location
        if package is None and container_deployment:
            package = self._container_adapter.last_directory
        language = code_package.language_name
        benchmark = code_package.benchmark

        # Update the worker with all package files
        account_id = worker.account_id or self.config.credentials.account_id
        if not account_id:
            raise RuntimeError("Account ID is required to update worker")

        # For container deployments, skip redeployment if code hasn't changed
        # Containers don't support runtime memory configuration changes
        # Detect container deployment by checking if worker name starts with "container-"
        is_container = worker.name.startswith("container-")
        
        if is_container:
            self.logging.info(f"Skipping redeployment for container worker {worker.name} - containers don't support runtime memory updates")
        else:
            self._create_or_update_worker(worker.name, package, account_id, language, benchmark, code_package, container_deployment, container_uri)
            self.logging.info(f"Updated worker {worker.name}")

        # Update configuration if needed (no-op for containers since they don't support runtime memory changes)
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
        self.logging.warning(
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
        name = (
            f"{code_package.benchmark}-{code_package.language_name}-"
            f"{code_package.language_version.replace('.', '')}"
        ).lower()
        if code_package.language_variant != "default":
            name = f"{name}-{code_package.language_variant}"
        return name

    @staticmethod
    def format_function_name(name: str, container_deployment: bool = False) -> str:
        """
        Format a function name to comply with Cloudflare Worker naming rules.

        Worker names must:
        - Be lowercase
        - Contain only alphanumeric characters and hyphens
        - Not start or end with a hyphen
        - Not start with a digit

        Args:
            name: The original name
            container_deployment: Whether this is a container worker (adds 'w-' prefix if name starts with digit)

        Returns:
            Formatted name
        """
        # Convert to lowercase and replace invalid characters
        formatted = name.lower().replace('_', '-').replace('.', '-')
        # Remove any characters that aren't alphanumeric or hyphen
        formatted = ''.join(c for c in formatted if c.isalnum() or c == '-')
        # Remove leading/trailing hyphens
        formatted = formatted.strip('-')
        # Ensure container worker names don't start with a digit (Cloudflare requirement)
        # Only add prefix for container workers to differentiate from native workers
        if container_deployment and formatted and formatted[0].isdigit():
            formatted = 'container-' + formatted
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
        raise NotImplementedError(
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
            if result.stats.memory_used is not None and result.stats.memory_used > 0:
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
        from sebs.cloudflare.triggers import HTTPTrigger

        worker = cast(CloudflareWorker, function)

        if trigger_type == Trigger.TriggerType.HTTP:
            account_id = worker.account_id or self.config.credentials.account_id
            worker_url = self._build_workers_dev_url(worker.name, account_id)
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

        Saves configuration to cache and shuts down deployment handler CLI containers.
        """
        try:
            self.cache_client.lock()
            self.config.update_cache(self.cache_client)
        finally:
            self.cache_client.unlock()
        
        # Shutdown deployment handler CLI containers
        self._workers_deployment.shutdown()
        self._containers_deployment.shutdown()

"""
Cloudflare Container Workers deployment implementation.

Handles packaging, Docker image building, and deployment of containerized
Cloudflare Workers using @cloudflare/containers.
"""

import os
import shutil
import json
import subprocess

import time
from importlib.resources import files
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Fallback for older Python
try:
    import tomli_w
except ImportError:
    # Fallback to basic TOML writing if tomli_w not available
    import toml as tomli_w
from typing import Optional, Tuple

import requests

from sebs.benchmark import Benchmark
from sebs.cloudflare.cli import CloudflareCLI
from sebs.utils import get_resource_path


class CloudflareContainersDeployment:
    """Handles Cloudflare container worker deployment operations."""

    def __init__(self, logging, system_config, docker_client, system_resources):
        """
        Initialize CloudflareContainersDeployment.

        Args:
            logging: Logger instance
            system_config: System configuration
            docker_client: Docker client instance
            system_resources: System resources manager
        """
        self.logging = logging
        self.system_config = system_config
        self.docker_client = docker_client
        self.system_resources = system_resources
        self._base_image: Optional[str] = None
        self._cli: Optional[CloudflareCLI] = None

    def _get_cli(self) -> CloudflareCLI:
        """Get or initialize the Cloudflare CLI container."""
        if self._cli is None:
            self._cli = CloudflareCLI.get_instance(self.system_config, self.docker_client)
            # Verify wrangler is available
            version = self._cli.check_wrangler_version()
            self.logging.info(f"Cloudflare CLI container ready: {version}")
        return self._cli

    def generate_wrangler_toml(
        self,
        worker_name: str,
        package_dir: str,
        language: str,
        account_id: str,
        benchmark_name: Optional[str] = None,
        code_package: Optional[Benchmark] = None,
        container_uri: str = "",
        language_variant: str = "default",
    ) -> str:
        """
        Generate a wrangler.toml configuration file for container workers.

        Args:
            worker_name: Name of the worker
            package_dir: Directory containing the worker code
            language: Programming language (nodejs or python)
            account_id: Cloudflare account ID
            benchmark_name: Optional benchmark name for R2 file path prefix
            code_package: Optional benchmark package for nosql configuration
            container_uri: Container image URI/tag

        Returns:
            Path to the generated wrangler.toml file
        """
        # Load template
        template_path = files("sebs.cloudflare").joinpath("templates", "wrangler-container.toml")
        with open(template_path, 'rb') as f:
            config = tomllib.load(f)

        # Update basic configuration
        config['name'] = worker_name
        config['account_id'] = account_id

        if container_uri and container_uri.startswith("registry.cloudflare.com"):
            # Pre-built image already pushed to Cloudflare registry — point wrangler
            # at it directly so it skips the Docker build step entirely.
            config['containers'][0]['image'] = container_uri
        else:
            # Fallback: let wrangler build from the local Dockerfile.
            if self._base_image:
                config['containers'][0]['build_args'] = {"BASE_IMAGE": self._base_image}

        # Update container configuration with instance type if needed
        if benchmark_name and ("411.image-recognition" in benchmark_name or 
                              "311.compression" in benchmark_name or 
                              "504.dna-visualisation" in benchmark_name):
            self.logging.warning("Using standard-4 instance type for high resource benchmark")
            config['containers'][0]['instance_type'] = "standard-4"
        
        # Add nosql KV namespace bindings if benchmark uses them
        if code_package and code_package.uses_nosql:
            # Get registered nosql tables for this benchmark
            nosql_storage = self.system_resources.get_nosql_storage()
            benchmark_for_nosql = benchmark_name or code_package.benchmark
            if nosql_storage.retrieve_cache(benchmark_for_nosql):
                nosql_tables = nosql_storage.get_tables(benchmark_for_nosql)
                if nosql_tables:
                    config['kv_namespaces'] = config.get('kv_namespaces', [])
                    for table_name, namespace_id in nosql_tables.items():
                        config['kv_namespaces'].append({
                            'binding': table_name,
                            'id': namespace_id,
                        })
        
        # Add environment variables
        if benchmark_name or (code_package and code_package.uses_nosql):
            config['vars'] = {}
            if benchmark_name:
                config['vars']['BENCHMARK_NAME'] = benchmark_name
            if code_package and code_package.uses_nosql:
                config['vars']['NOSQL_STORAGE_DATABASE'] = "kvstore"
        
        # Add R2 bucket binding
        from sebs.faas.config import Resources
        storage = self.system_resources.get_storage()
        bucket_name = storage.get_bucket(Resources.StorageBucketType.BENCHMARKS)
        if not bucket_name:
            raise RuntimeError(
                "R2 bucket binding not configured: benchmarks bucket name is empty. "
                "Benchmarks requiring file access will not work properly."
            )
        config['r2_buckets'] = [{
            'binding': 'R2',
            'bucket_name': bucket_name
        }]
        self.logging.info(f"R2 bucket '{bucket_name}' will be bound to worker as 'R2'")
        
        # Write wrangler.toml to package directory
        toml_path = os.path.join(package_dir, "wrangler.toml")
        try:
            # Try tomli_w (writes binary)
            with open(toml_path, 'wb') as f:
                tomli_w.dump(config, f)
        except TypeError:
            # Fallback to toml library (writes text)
            with open(toml_path, 'w') as f:
                f.write(tomli_w.dumps(config))
        
        self.logging.info(f"Generated wrangler.toml at {toml_path}")
        return toml_path

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
    ) -> Tuple[str, int, str]:
        """
        Package code for Cloudflare container worker deployment.
        
        Builds a Docker image and returns the image tag for deployment.

        Args:
            directory: Path to the code directory
            language_name: Programming language name
            language_version: Programming language version
            architecture: Target architecture
            benchmark: Benchmark name

        Returns:
            Tuple of (package_path, package_size, container_uri)
        """
        self.logging.info(f"Packaging container for {language_name} {language_version}")

        # Get wrapper directory for container files
        wrapper_base = str(get_resource_path("benchmarks", "wrappers", "cloudflare"))
        wrapper_container_dir = os.path.join(wrapper_base, language_name, "container")

        if not os.path.exists(wrapper_container_dir):
            raise RuntimeError(
                f"Container wrapper directory not found: {wrapper_container_dir}"
            )

        # Overwrite the wrapper files staged by add_deployment_files() with the
        # container-specific versions before doing anything else.
        if language_name == "python":
            for f in ["handler.py", "storage.py", "nosql.py"]:
                src = os.path.join(wrapper_container_dir, f)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(directory, f))

        # For Python: move benchmark code into function/ so that relative imports
        # work natively, matching the workers and AWS layout.
        # handler.py and requirements.txt* stay at the top level.
        if language_name == "python":
            func_dir = os.path.join(directory, "function")
            os.makedirs(func_dir, exist_ok=True)
            open(os.path.join(func_dir, "__init__.py"), "w").close()
            dont_move = {"function", "handler.py"}
            for item in os.listdir(directory):
                if item in dont_move or item.startswith("requirements"):
                    continue
                shutil.move(os.path.join(directory, item), os.path.join(func_dir, item))
                self.logging.info(f"Moved {item} into function/ package")

        # Copy Dockerfile.function from dockerfiles/cloudflare/{language}/
        dockerfile_src = str(
            get_resource_path(
                "dockerfiles", "cloudflare", language_name, "Dockerfile.function"
            )
        )
        dockerfile_dest = os.path.join(directory, "Dockerfile")
        if os.path.exists(dockerfile_src):
            # Get base image from systems.json for container deployments
            container_images = self.system_config.benchmark_container_images(
                "cloudflare", language_name, architecture
            )
            base_image = container_images.get(language_version)
            if not base_image:
                raise RuntimeError(
                    f"No container base image found in systems.json for {language_name} {language_version} on {architecture}"
                )
            self._base_image = base_image

            shutil.copy2(dockerfile_src, dockerfile_dest)
            self.logging.info(f"Copied Dockerfile from {dockerfile_src}")

        # For nodejs, copy the container handler (no function/ subdir for nodejs).
        if language_name == "nodejs":
            handler_file = "handler.js"
            shutil.copy2(
                os.path.join(wrapper_container_dir, handler_file),
                os.path.join(directory, handler_file),
            )
            self.logging.info(f"Copied container {handler_file}")

        nodejs_wrapper_dir = os.path.join(wrapper_base, "nodejs", "container")
        worker_js_src = os.path.join(nodejs_wrapper_dir, "worker.js")
        if os.path.exists(worker_js_src):
            shutil.copy2(worker_js_src, os.path.join(directory, "worker.js"))
            self.logging.info(f"Copied worker.js orchestration file from nodejs/container")

        # Copy init.sh if the benchmark needs it (e.g. video-processing downloads ffmpeg)
        from sebs.utils import find_benchmark
        benchmark_path = find_benchmark(benchmark, "benchmarks")
        if benchmark_path:
            for path in [benchmark_path, os.path.join(benchmark_path, language_name)]:
                init_sh = os.path.join(path, "init.sh")
                if os.path.exists(init_sh):
                    shutil.copy2(init_sh, os.path.join(directory, "init.sh"))
                    self.logging.info(f"Copied init.sh from {path}")
                    break

        # ALL containers need @cloudflare/containers for worker.js orchestration.
        # For nodejs benchmarks, preserve the existing package.json and add the
        # dependency. For Python, create a minimal package.json with just the dep.
        package_json_path = os.path.join(directory, "package.json")
        if language_name == "nodejs":
            if not os.path.exists(package_json_path):
                raise RuntimeError(
                    f"package.json not found at {package_json_path} "
                    f"for nodejs benchmark '{benchmark}'"
                )
            with open(package_json_path, 'r') as f:
                package_json = json.load(f)
        else:
            package_json = {}
        package_json.setdefault("dependencies", {})["@cloudflare/containers"] = "*"
        with open(package_json_path, 'w') as f:
            json.dump(package_json, f, indent=2)

        # For Python containers, promote the versioned requirements.txt to requirements.txt
        if language_name == "python":
            requirements_file = os.path.join(directory, "requirements.txt")
            versioned_requirements = os.path.join(directory, f"requirements.txt.{language_version}")
            if os.path.exists(versioned_requirements):
                shutil.copy2(versioned_requirements, requirements_file)
                self.logging.info(f"Copied requirements.txt.{language_version} to requirements.txt")
            elif not os.path.exists(requirements_file):
                open(requirements_file, "w").close()
                self.logging.info("Created empty requirements.txt")
        
        # Build the image locally. cache.py requires docker_client.images.get() to
        # succeed for container deployments, and the local image is what we push to
        # Cloudflare's registry during deploy (wrangler containers push).
        image_tag = self._build_container_image_local(
            directory, benchmark, language_name, language_version
        )

        # Calculate package size (approximate, as it's a source directory)
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        self.logging.info(f"Container package prepared (image tag: {image_tag})")

        return (directory, total_size, image_tag)
    
    def _build_container_image_local(
        self,
        directory: str,
        benchmark: str,
        language_name: str,
        language_version: str,
    ) -> str:
        """
        Build the container image locally.

        The local image is pushed to Cloudflare's registry via
        `wrangler containers push` during deployment, so wrangler deploy can
        reference it directly without rebuilding from the Dockerfile.

        Returns the local image tag.
        """
        # Generate image tag
        image_name = f"{benchmark.replace('.', '-')}-{language_name}-{language_version.replace('.', '')}"
        image_tag = f"{image_name}:latest"

        self.logging.info(f"Building container image {image_tag} for linux/amd64...")

        result = subprocess.run(
            [
                "docker", "buildx", "build",
                "--platform", "linux/amd64",
                "--load",
                "--no-cache",
                "-t", image_tag,
                directory,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.logging.error(result.stderr)
            raise RuntimeError(f"Docker build failed for {image_tag}:\n{result.stderr}")

        self.logging.info(f"Container image built: {image_tag}")
        return image_tag

    def wait_for_container_worker_ready(
        self,
        worker_name: str,
        worker_url: str,
        max_wait_seconds: int = 400
    ) -> bool:
        """
        Wait for container worker to be fully provisioned and ready.

        Args:
            worker_name: Name of the worker
            worker_url: URL of the worker
            max_wait_seconds: Maximum time to wait in seconds

        Returns:
            True if ready, False if timeout
        """
        wait_interval = 10
        start_time = time.time()
        
        self.logging.info("Checking container worker readiness via health endpoint...")
        
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        while time.time() - start_time < max_wait_seconds:
            try:
                # Use health check endpoint
                response = requests.get(
                    f"{worker_url}/health",
                    timeout=60
                )
                
                # 200 = ready
                if response.status_code == 200:
                    self.logging.info("Container worker is ready!")
                    return True
                # 503 = not ready yet
                elif response.status_code == 503:
                    elapsed = int(time.time() - start_time)
                    self.logging.info(
                        f"Container worker not ready yet (503 Service Unavailable)... "
                        f"({elapsed}s elapsed, will retry)"
                    )
                # Other errors
                else:
                    self.logging.warning(f"Unexpected status {response.status_code}: {response.text[:100]}")
                    
            except requests.exceptions.Timeout:
                elapsed = int(time.time() - start_time)
                self.logging.info(f"Health check timeout (container may be starting)... ({elapsed}s elapsed)")
            except requests.exceptions.RequestException as e:
                elapsed = int(time.time() - start_time)
                self.logging.debug(f"Connection error ({elapsed}s): {str(e)[:100]}")
            
            time.sleep(wait_interval)
        
        raise RuntimeError(
            f"Container worker {worker_name} did not become ready after {max_wait_seconds}s. "
            "Deployment cannot proceed without a healthy container."
        )

    def shutdown(self):
        """Shutdown CLI container if initialized."""
        if self._cli is not None:
            self._cli.shutdown()
            self._cli = None

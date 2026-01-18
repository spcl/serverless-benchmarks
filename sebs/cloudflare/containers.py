"""
Cloudflare Container Workers deployment implementation.

Handles packaging, Docker image building, and deployment of containerized
Cloudflare Workers using @cloudflare/containers.
"""

import os
import shutil
import json
import io
import re
import time
import tarfile
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

import docker
import requests

from sebs.benchmark import Benchmark
from sebs.cloudflare.cli import CloudflareCLI


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
        self._cli: Optional[CloudflareCLI] = None

    def _get_cli(self) -> CloudflareCLI:
        """Get or initialize the Cloudflare CLI container."""
        if self._cli is None:
            self._cli = CloudflareCLI(self.system_config, self.docker_client)
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
        template_path = os.path.join(
            os.path.dirname(__file__), 
            "../..", 
            "templates", 
            "wrangler-container.toml"
        )
        with open(template_path, 'rb') as f:
            config = tomllib.load(f)
        
        # Update basic configuration
        config['name'] = worker_name
        config['account_id'] = account_id
        
        # Update container configuration with instance type if needed
        if benchmark_name and ("411.image-recognition" in benchmark_name or 
                              "311.compression" in benchmark_name or 
                              "504.dna-visualisation" in benchmark_name):
            self.logging.warning("Using standard-4 instance type for high resource benchmark")
            config['containers'][0]['instance_type'] = "standard-4"
        
        # Add nosql table bindings if benchmark uses them
        if code_package and code_package.uses_nosql:
            # Get registered nosql tables for this benchmark
            nosql_storage = self.system_resources.get_nosql_storage()
            if nosql_storage.retrieve_cache(benchmark_name):
                nosql_tables = nosql_storage._tables.get(benchmark_name, {})
                
                # Add durable object bindings for each nosql table
                for table_name in nosql_tables.keys():
                    config['durable_objects']['bindings'].append({
                        'name': table_name.upper(),
                        'class_name': 'KVApiObject'
                    })
                
                # Update migrations to include KVApiObject
                config['migrations'][0]['new_sqlite_classes'].append('KVApiObject')
        
        # Add environment variables
        if benchmark_name or (code_package and code_package.uses_nosql):
            config['vars'] = {}
            if benchmark_name:
                config['vars']['BENCHMARK_NAME'] = benchmark_name
            if code_package and code_package.uses_nosql:
                config['vars']['NOSQL_STORAGE_DATABASE'] = "durable_objects"
        
        # Add R2 bucket binding
        try:
            from sebs.faas.config import Resources
            storage = self.system_resources.get_storage()
            bucket_name = storage.get_bucket(Resources.StorageBucketType.BENCHMARKS)
            if bucket_name:
                config['r2_buckets'] = [{
                    'binding': 'R2',
                    'bucket_name': bucket_name
                }]
                self.logging.info(f"R2 bucket '{bucket_name}' will be bound to worker as 'R2'")
        except Exception as e:
            self.logging.warning(
                f"R2 bucket binding not configured: {e}. "
                f"Benchmarks requiring file access will not work properly."
            )
        
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
        wrapper_base = os.path.join(
            os.path.dirname(__file__), "..", "..", "benchmarks", "wrappers", "cloudflare"
        )
        wrapper_container_dir = os.path.join(wrapper_base, language_name, "container")
        
        if not os.path.exists(wrapper_container_dir):
            raise RuntimeError(
                f"Container wrapper directory not found: {wrapper_container_dir}"
            )
        
        # Copy container wrapper files to the package directory
        # Copy Dockerfile from dockerfiles/cloudflare/{language}/
        dockerfile_src = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "dockerfiles",
            "cloudflare",
            language_name,
            "Dockerfile"
        )
        dockerfile_dest = os.path.join(directory, "Dockerfile")
        if os.path.exists(dockerfile_src):
            # Read Dockerfile and update BASE_IMAGE based on language version
            with open(dockerfile_src, 'r') as f:
                dockerfile_content = f.read()
            
            # Get base image from systems.json for container deployments
            container_images = self.system_config.benchmark_container_images(
                "cloudflare", language_name, architecture
            )
            base_image = container_images.get(language_version)
            if not base_image:
                raise RuntimeError(
                    f"No container base image found in systems.json for {language_name} {language_version} on {architecture}"
                )
            
            # Replace BASE_IMAGE default value in ARG line
            dockerfile_content = re.sub(
                r'ARG BASE_IMAGE=.*',
                f'ARG BASE_IMAGE={base_image}',
                dockerfile_content
            )
            
            # Write modified Dockerfile
            with open(dockerfile_dest, 'w') as f:
                f.write(dockerfile_content)
            
            self.logging.info(f"Copied Dockerfile from {dockerfile_src}")
        else:
            raise RuntimeError(f"Dockerfile not found at {dockerfile_src}")
        
        # Copy handler and utility files from wrapper/container
        # Note: ALL containers use worker.js for orchestration (@cloudflare/containers is Node.js only)
        # The handler inside the container can be Python or Node.js
        container_files = ["handler.py" if language_name == "python" else "handler.js"]
        
        # For worker.js orchestration file, always use the nodejs version
        nodejs_wrapper_dir = os.path.join(wrapper_base, "nodejs", "container")
        worker_js_src = os.path.join(nodejs_wrapper_dir, "worker.js")
        worker_js_dest = os.path.join(directory, "worker.js")
        if os.path.exists(worker_js_src):
            shutil.copy2(worker_js_src, worker_js_dest)
            self.logging.info(f"Copied worker.js orchestration file from nodejs/container")
        
        # Copy storage and nosql utilities from language-specific wrapper
        if language_name == "nodejs":
            container_files.extend(["storage.js", "nosql.js"])
        else:
            container_files.extend(["storage.py", "nosql.py"])
        
        for file in container_files:
            src = os.path.join(wrapper_container_dir, file)
            dest = os.path.join(directory, file)
            if os.path.exists(src):
                shutil.copy2(src, dest)
                self.logging.info(f"Copied container file: {file}")
        
        # Check if benchmark has init.sh and copy it (needed for some benchmarks like video-processing)
        # Look in both the benchmark root and the language-specific directory
        from sebs.utils import find_benchmark
        benchmark_path = find_benchmark(benchmark, "benchmarks")
        if benchmark_path:
            paths = [
                benchmark_path,
                os.path.join(benchmark_path, language_name),
            ]
            for path in paths:
                init_sh = os.path.join(path, "init.sh")
                if os.path.exists(init_sh):
                    shutil.copy2(init_sh, os.path.join(directory, "init.sh"))
                    self.logging.info(f"Copied init.sh from {path}")
                    break
        
        # For Python containers, fix relative imports in benchmark code
        # Containers use flat structure, so "from . import storage" must become "import storage"
        if language_name == "python":
            for item in os.listdir(directory):
                if item.endswith('.py') and item not in ['handler.py', 'storage.py', 'nosql.py', 'worker.py']:
                    file_path = os.path.join(directory, item)
                    with open(file_path, 'r') as f:
                        content = f.read()
                    # Fix relative imports
                    content = re.sub(r'from \. import ', 'import ', content)
                    with open(file_path, 'w') as f:
                        f.write(content)
        
        # For Node.js containers, transform benchmark code to be async-compatible
        # The container wrapper uses async HTTP calls, but benchmarks expect sync
        elif language_name == "nodejs":
            for item in os.listdir(directory):
                if item.endswith('.js') and item not in ['handler.js', 'storage.js', 'nosql.js', 'worker.js', 'build.js', 'request-polyfill.js']:
                    file_path = os.path.join(directory, item)
                    # Could add transformations here if needed
                    pass
        
        # Prepare package.json for container orchestration
        # ALL containers need @cloudflare/containers for worker.js orchestration
        worker_package_json = {
            "name": f"{benchmark}-worker",
            "version": "1.0.0",
            "dependencies": {
                "@cloudflare/containers": "*"
            }
        }
        
        if language_name == "nodejs":
            # Read the benchmark's package.json if it exists and merge dependencies
            benchmark_package_file = os.path.join(directory, "package.json")
            if os.path.exists(benchmark_package_file):
                with open(benchmark_package_file, 'r') as f:
                    benchmark_package = json.load(f)
                # Merge dependencies
                if "dependencies" in benchmark_package:
                    worker_package_json["dependencies"].update(benchmark_package["dependencies"])
            
            # Write the combined package.json
            with open(benchmark_package_file, 'w') as f:
                json.dump(worker_package_json, f, indent=2)
        else:  # Python containers also need package.json for worker.js orchestration
            # Create package.json just for @cloudflare/containers (Python code in container)
            package_json_path = os.path.join(directory, "package.json")
            with open(package_json_path, 'w') as f:
                json.dump(worker_package_json, f, indent=2)
        
        # Install Node.js dependencies for wrangler deployment
        # Note: These are needed for wrangler to bundle worker.js, not for the container
        # The container also installs them during Docker build
        self.logging.info(f"Installing Node.js dependencies for wrangler deployment in {directory}")
        cli = self._get_cli()
        container_path = f"/tmp/container_npm/{os.path.basename(directory)}"
        
        try:
            # Upload package directory to CLI container
            cli.upload_package(directory, container_path)
            
            # Install production dependencies
            output = cli.execute(f"cd {container_path} && npm install --production")
            self.logging.info("npm install completed successfully")
            self.logging.debug(f"npm output: {output.decode('utf-8')}")
            
            # Download node_modules back to host for wrangler
            bits, stat = cli.docker_instance.get_archive(f"{container_path}/node_modules")
            file_obj = io.BytesIO()
            for chunk in bits:
                file_obj.write(chunk)
            file_obj.seek(0)
            with tarfile.open(fileobj=file_obj) as tar:
                tar.extractall(directory)
            
            self.logging.info(f"Downloaded node_modules to {directory} for wrangler deployment")
        except Exception as e:
            self.logging.error(f"npm install failed: {e}")
            raise RuntimeError(f"Failed to install Node.js dependencies: {e}")
        
        # For Python containers, also handle Python requirements
        if language_name == "python":
            # Python requirements will be installed in the Dockerfile
            # Rename version-specific requirements.txt to requirements.txt
            requirements_file = os.path.join(directory, "requirements.txt")
            versioned_requirements = os.path.join(directory, f"requirements.txt.{language_version}")
            
            if os.path.exists(versioned_requirements):
                shutil.copy2(versioned_requirements, requirements_file)
                self.logging.info(f"Copied requirements.txt.{language_version} to requirements.txt")
                
                # Fix torch wheel URLs for container compatibility
                # Replace direct wheel URLs with proper torch installation
                with open(requirements_file, 'r') as f:
                    content = f.read()
                
                # Replace torch wheel URLs with proper installation commands
                modified = False
                if 'download.pytorch.org/whl' in content:
                    # Replace direct wheel URL with pip-installable torch
                    content = re.sub(
                        r'https://download\.pytorch\.org/whl/[^\s]+\.whl',
                        'torch',
                        content
                    )
                    modified = True
                
                if modified:
                    with open(requirements_file, 'w') as f:
                        f.write(content)
                    self.logging.info("Fixed torch URLs in requirements.txt for container compatibility")
                
            elif not os.path.exists(requirements_file):
                # Create empty requirements.txt if none exists
                with open(requirements_file, 'w') as f:
                    f.write("")
                self.logging.info("Created empty requirements.txt")
        
        # Build Docker image locally for cache compatibility
        # wrangler will re-build/push during deployment from the Dockerfile
        image_tag = self._build_container_image_local(directory, benchmark, language_name, language_version)
        
        # Calculate package size (approximate, as it's a source directory)
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)
        
        self.logging.info(f"Container package prepared with local image: {image_tag}")
        
        # Return local image tag (wrangler will rebuild from Dockerfile during deploy)
        return (directory, total_size, image_tag)
    
    def _build_container_image_local(
        self,
        directory: str,
        benchmark: str,
        language_name: str,
        language_version: str,
    ) -> str:
        """
        Build a Docker image locally for cache purposes.
        wrangler will rebuild from Dockerfile during deployment.
        
        Returns the local image tag.
        """
        # Generate image tag
        image_name = f"{benchmark.replace('.', '-')}-{language_name}-{language_version.replace('.', '')}"
        image_tag = f"{image_name}:latest"
        
        self.logging.info(f"Building local container image: {image_tag}")
        
        try:
            # Build the Docker image using docker-py
            # nocache=True ensures handler changes are picked up
            _, build_logs = self.docker_client.images.build(
                path=directory,
                tag=image_tag,
                nocache=True,
                rm=True
            )
            
            # Log build output
            for log in build_logs:
                if 'stream' in log:
                    self.logging.debug(log['stream'].strip())
                elif 'error' in log:
                    self.logging.error(log['error'])
            
            self.logging.info(f"Local container image built: {image_tag}")
            
            return image_tag
            
        except docker.errors.BuildError as e:
            error_msg = f"Docker build failed for {image_tag}: {e}"
            self.logging.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error building Docker image {image_tag}: {e}"
            self.logging.error(error_msg)
            raise RuntimeError(error_msg)

    def wait_for_durable_object_ready(
        self,
        worker_name: str,
        worker_url: str,
        max_wait_seconds: int = 400
    ) -> bool:
        """
        Wait for container Durable Object to be fully provisioned and ready.

        Args:
            worker_name: Name of the worker
            worker_url: URL of the worker
            max_wait_seconds: Maximum time to wait in seconds

        Returns:
            True if ready, False if timeout
        """
        wait_interval = 10
        start_time = time.time()
        
        self.logging.info("Checking container Durable Object readiness via health endpoint...")
        
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
                    self.logging.info("Container Durable Object is ready!")
                    return True
                # 503 = not ready yet
                elif response.status_code == 503:
                    elapsed = int(time.time() - start_time)
                    self.logging.info(
                        f"Container Durable Object not ready yet (503 Service Unavailable)... "
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
        
        self.logging.warning(
            f"Container Durable Object may not be fully ready after {max_wait_seconds}s. "
            "First invocation may still experience initialization delay."
        )
        return False

    def shutdown(self):
        """Shutdown CLI container if initialized."""
        if self._cli is not None:
            self._cli.shutdown()
            self._cli = None

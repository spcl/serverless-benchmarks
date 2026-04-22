"""
Cloudflare Workers native deployment implementation.

Handles packaging, deployment, and management of native Cloudflare Workers
(non-container deployments using JavaScript/Python runtime).
"""

import os
import re
import shutil
import json
import io
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

from sebs.benchmark import Benchmark
from sebs.cloudflare.cli import CloudflareCLI
from sebs.cloudflare.pyodide_packages import get_canonical_pyodide_name
from sebs.utils import get_resource_path


class CloudflareWorkersDeployment:
    """Handles native Cloudflare Workers deployment operations."""

    def __init__(self, logging, system_config, docker_client, system_resources):
        """
        Initialize CloudflareWorkersDeployment.

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
        language_variant: str = "cloudflare",
    ) -> str:
        """
        Generate a wrangler.toml configuration file for native workers.

        Args:
            worker_name: Name of the worker
            package_dir: Directory containing the worker code
            language: Programming language (nodejs or python)
            account_id: Cloudflare account ID
            benchmark_name: Optional benchmark name for R2 file path prefix
            code_package: Optional benchmark package for nosql configuration

        Returns:
            Path to the generated wrangler.toml file
        """
        # Load template
        template_path = os.path.join(
            os.path.dirname(__file__),
            "templates",
            "wrangler-worker.toml"
        )
        with open(template_path, 'rb') as f:
            config = tomllib.load(f)

        # Update basic configuration
        config['name'] = worker_name
        config['account_id'] = account_id

        # Add language- and variant-specific configuration.
        # For Node.js workers, we always bundle through build.js into dist/,
        # regardless of language variant (default/cloudflare), because the
        # wrangler entrypoint points to dist/handler.js.
        if language == "nodejs":
            config['main'] = "dist/handler.js"
            config['compatibility_flags'] = ["nodejs_compat"]
            config['no_bundle'] = True
            config['rules'] = [
                {
                    'type': 'ESModule',
                    'globs': ['**/*.js'],
                    'fallthrough': True
                },
                {
                    'type': 'Text',
                    'globs': ['**/*.html'],
                    'fallthrough': True
                }
            ]
        elif language == "python":
            config['main'] = "handler.py"
            config['compatibility_flags'] = ["python_workers"]
        else:
            config['main'] = "dist/handler.js" if language == "nodejs" else "handler.py"

        # Add NoSQL KV namespace bindings if benchmark uses them
        if code_package and code_package.uses_nosql:
            benchmark_for_nosql = benchmark_name or code_package.benchmark
            nosql_storage = self.system_resources.get_nosql_storage()
            if nosql_storage.retrieve_cache(benchmark_for_nosql):
                nosql_tables = nosql_storage.get_tables(benchmark_for_nosql)
                if nosql_tables:
                    config['kv_namespaces'] = []
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
        os.makedirs(package_dir, exist_ok=True)
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
        benchmark: str,
        is_cached: bool,
        language_variant: str = "cloudflare",
    ) -> Tuple[str, int, str]:
        """
        Package code for native Cloudflare Workers deployment.

        Args:
            directory: Path to the code directory
            language_name: Programming language name
            language_version: Programming language version
            benchmark: Benchmark name
            is_cached: Whether the code is cached

        Returns:
            Tuple of (package_path, package_size, container_uri)
        """
        # Install dependencies and bundle
        if language_name == "nodejs":
            # Build via Dockerfile.build (npm install + esbuild + __require patching),
            # then extract the produced dist/ back into the package directory.
            # This mirrors how container deployments use their Dockerfile.function — the
            # only difference is which Dockerfile is selected.
            self._build_worker_and_extract_dist(directory, is_cached)

        elif language_name == "python":
            requirements_file = os.path.join(directory, "requirements.txt")
            if os.path.exists(f"{requirements_file}.{language_version}"):
                src = f"{requirements_file}.{language_version}"
                dest = requirements_file
                shutil.move(src, dest)
                self.logging.info(f"move {src} to {dest}")

            if language_variant in ("cloudflare", "default"):
                if os.path.exists(requirements_file):
                    with open(requirements_file, 'r') as reqf:
                        reqtext = reqf.read()
                    needed_pkg = []
                    unsupported = []
                    seen = set()
                    for raw_line in reqtext.splitlines():
                        line = raw_line.split("#", 1)[0].strip()
                        if not line:
                            continue
                        name = re.split(r"[<>=!~;\s\[]", line, maxsplit=1)[0].strip()
                        if not name:
                            continue
                        canonical = get_canonical_pyodide_name(name)
                        if canonical is None:
                            unsupported.append(name)
                            continue
                        if canonical not in seen:
                            needed_pkg.append(canonical)
                            seen.add(canonical)
                    if unsupported:
                        raise RuntimeError(
                            "The following packages from requirements.txt are not "
                            "supported by the Cloudflare Python Workers (Pyodide) "
                            f"runtime: {', '.join(unsupported)}. See "
                            "https://developers.cloudflare.com/workers/languages/python/packages/ "
                            "for the list of supported packages."
                        )

                    project_file = os.path.join(directory, "pyproject.toml")
                    pyproject_config = {
                        "project": {
                            "name": f"{benchmark.replace('.', '-')}-python-"
                                    f"{language_version.replace('.', '')}",
                            "version": "0.1.0",
                            "description": "dummy description",
                            "requires-python": f">={language_version}",
                            "dependencies": needed_pkg,
                        },
                        "dependency-groups": {
                            "dev": ["workers-py", "workers-runtime-sdk"],
                        },
                    }
                    try:
                        with open(project_file, 'wb') as pf:
                            tomli_w.dump(pyproject_config, pf)
                    except TypeError:
                        with open(project_file, 'w') as pf:
                            pf.write(tomli_w.dumps(pyproject_config))
                # Pyodide Workers require all function files in a function/ subdir
                funcdir = os.path.join(directory, "function")
                if not os.path.exists(funcdir):
                    os.makedirs(funcdir)

                dont_move = ["handler.py", "function", "python_modules", "pyproject.toml"]
                for thing in os.listdir(directory):
                    if thing not in dont_move:
                        src = os.path.join(directory, thing)
                        dest = os.path.join(directory, "function", thing)
                        shutil.move(src, dest)

                # Early validation: build Dockerfile.build to confirm the
                # generated pyproject.toml parses and the workers-py toolchain
                # is wired up.  Deploy still runs pywrangler from Dockerfile.manage.
                self._build_python_worker(directory, is_cached)

        # Create package structure
        CONFIG_FILES = {
            "nodejs": ["handler.js", "package.json", "node_modules"],
            "python": ["handler.py", "requirements.txt", "python_modules"],
        }

        if language_name not in CONFIG_FILES:
            raise NotImplementedError(
                f"Language {language_name} is not yet supported for Cloudflare Workers"
            )

        # Verify the handler exists
        handler_file = "handler.js" if language_name == "nodejs" else "handler.py"
        package_path = os.path.join(directory, handler_file)

        if not os.path.exists(package_path):
            if not os.path.exists(directory):
                raise RuntimeError(
                    f"Package directory {directory} does not exist. "
                    "The benchmark build process may have failed to create the deployment package."
                )
            raise RuntimeError(
                f"Handler file {handler_file} not found in {directory}. "
                f"Available files: {', '.join(os.listdir(directory)) if os.path.exists(directory) else 'none'}"
            )

        # Calculate total size of the package directory
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        mbytes = total_size / 1024.0 / 1024.0
        self.logging.info(f"Worker package size: {mbytes:.2f} MB (Python: missing vendored modules)")

        return (directory, total_size, "")

    def _build_worker_and_extract_dist(self, directory: str, is_cached: bool) -> None:
        """Build the Node.js worker bundle via Dockerfile.build and extract dist/.

        Runs npm install, esbuild (build.js), and the __require→import post-
        processing step (postprocess.js) inside a throwaway Docker image built
        from Dockerfile.build.  Only the resulting dist/ directory is extracted
        back to *directory*; intermediate artifacts (node_modules, build image)
        stay inside Docker.

        If *is_cached* is True and dist/ already exists the build is skipped.
        """
        import docker as docker_module

        dist_dir = os.path.join(directory, "dist")
        if is_cached and os.path.exists(dist_dir):
            self.logging.info("Cached dist/ found — skipping worker bundle build.")
            return

        dockerfile_src = str(
            get_resource_path("dockerfiles", "cloudflare", "nodejs", "Dockerfile.build")
        )
        dockerfile_dest = os.path.join(directory, "Dockerfile.build")
        dockerignore_dest = os.path.join(directory, ".dockerignore")

        # Keep the build context lean: exclude generated / heavy artifacts.
        dockerignore_content = "node_modules\ndist\nDockerfile.build\n.dockerignore\n"
        shutil.copy2(dockerfile_src, dockerfile_dest)
        with open(dockerignore_dest, "w") as f:
            f.write(dockerignore_content)

        # Use base directory name + pid for a unique, collision-free tag.
        image_tag = f"sebs-worker-build-{os.path.basename(directory)}-{os.getpid()}:latest"

        try:
            self.logging.info(f"Building worker bundle via Dockerfile.build in {directory}")
            _, build_logs = self.docker_client.images.build(
                path=directory,
                dockerfile="Dockerfile.build",
                tag=image_tag,
                rm=True,
            )
            for log in build_logs:
                if "stream" in log:
                    self.logging.debug(log["stream"].strip())
                elif "error" in log:
                    raise RuntimeError(f"Docker build error: {log['error']}")

            # Extract dist/ from the built image.
            self.logging.info("Extracting built dist/ from worker build image...")
            container = self.docker_client.containers.create(image_tag)
            try:
                bits, _ = container.get_archive("/worker/dist")
                file_obj = io.BytesIO()
                for chunk in bits:
                    file_obj.write(chunk)
                file_obj.seek(0)
                if os.path.exists(dist_dir):
                    shutil.rmtree(dist_dir)
                with tarfile.open(fileobj=file_obj) as tar:
                    tar.extractall(directory)
                self.logging.info(f"dist/ extracted to {directory}")
            finally:
                container.remove()

        except docker_module.errors.BuildError as e:
            raise RuntimeError(f"Worker bundle build failed: {e}")
        finally:
            # Remove the temporary files we injected into the build context.
            for tmp in (dockerfile_dest, dockerignore_dest):
                if os.path.exists(tmp):
                    os.remove(tmp)
            try:
                self.docker_client.images.remove(image_tag, force=True)
            except Exception:
                pass

    def _build_python_worker(self, directory: str, is_cached: bool) -> None:
        """Validate a Python worker package via Dockerfile.build.

        Mirrors _build_worker_and_extract_dist for structural symmetry with
        the Node.js flow and with Dockerfile.build layouts in other clouds.
        Unlike Node.js (which needs esbuild + __require→import patching),
        Pyodide Worker deploys don't require a vendored bundle — Cloudflare
        resolves Pyodide packages server-side at deploy time via pywrangler.
        So this image only validates that the generated pyproject.toml parses
        and that workers-py is callable; nothing is extracted.

        A marker file is used for caching: once validation succeeds it is
        skipped on subsequent builds of the same directory.
        """
        import docker as docker_module

        marker = os.path.join(directory, ".build-validated")
        if is_cached and os.path.exists(marker):
            self.logging.info("Cached Python build marker — skipping validation.")
            return

        dockerfile_src = str(
            get_resource_path("dockerfiles", "cloudflare", "python", "Dockerfile.build")
        )
        dockerfile_dest = os.path.join(directory, "Dockerfile.build")
        dockerignore_dest = os.path.join(directory, ".dockerignore")

        dockerignore_content = (
            "python_modules\n.venv\nDockerfile.build\n.dockerignore\n"
        )
        shutil.copy2(dockerfile_src, dockerfile_dest)
        with open(dockerignore_dest, "w") as f:
            f.write(dockerignore_content)

        image_tag = f"sebs-python-build-{os.path.basename(directory)}-{os.getpid()}:latest"

        try:
            self.logging.info(
                f"Validating Python worker via Dockerfile.build in {directory}"
            )
            _, build_logs = self.docker_client.images.build(
                path=directory,
                dockerfile="Dockerfile.build",
                tag=image_tag,
                rm=True,
            )
            for log in build_logs:
                if "stream" in log:
                    self.logging.debug(log["stream"].strip())
                elif "error" in log:
                    raise RuntimeError(f"Docker build error: {log['error']}")

            with open(marker, "w") as f:
                f.write("ok")

        except docker_module.errors.BuildError as e:
            raise RuntimeError(f"Python worker validation failed: {e}")
        finally:
            for tmp in (dockerfile_dest, dockerignore_dest):
                if os.path.exists(tmp):
                    os.remove(tmp)
            try:
                self.docker_client.images.remove(image_tag, force=True)
            except Exception:
                pass

    def shutdown(self):
        """Shutdown CLI container if initialized."""
        if self._cli is not None:
            self._cli.shutdown()
            self._cli = None

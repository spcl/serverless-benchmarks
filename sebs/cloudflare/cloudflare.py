import os
import shutil
import json
import uuid
import subprocess
import time
from datetime import datetime
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
from sebs.faas.config import Resources


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
        # cached workers.dev subdomain for the account (e.g. 'marcin-copik')
        # This is different from the account ID and is required to build
        # public worker URLs like <name>.<subdomain>.workers.dev
        self._workers_dev_subdomain: Optional[str] = None

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

    def _ensure_wrangler_installed(self):
        """Ensure Wrangler CLI is installed and available."""
        try:
            result = subprocess.run(
                ["wrangler", "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            version = result.stdout.strip()
            self.logging.info(f"Wrangler is installed: {version}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logging.info("Wrangler not found, installing globally via npm...")
            try:
                result = subprocess.run(
                    ["npm", "install", "-g", "wrangler"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120
                )
                self.logging.info("Wrangler installed successfully")
                if result.stdout:
                    self.logging.debug(f"npm install wrangler output: {result.stdout}")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to install Wrangler: {e.stderr}")
            except FileNotFoundError:
                raise RuntimeError(
                    "npm not found. Please install Node.js and npm to use Wrangler for deployment."
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Wrangler version check timed out")

    def _ensure_pywrangler_installed(self):
        """Necessary to download python dependencies"""
        try:
            result = subprocess.run(
                ["pywrangler", "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            version = result.stdout.strip()
            self.logging.info(f"pywrangler is installed: {version}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logging.info("pywrangler not found, installing globally via uv tool install...")
            try:
                result = subprocess.run(
                    ["uv", "tool", "install", "workers-py"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120
                )
                self.logging.info("pywrangler installed successfully")
                if result.stdout:
                    self.logging.debug(f"uv tool install workers-py output: {result.stdout}")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to install pywrangler: {e.stderr}")
            except FileNotFoundError:
                raise RuntimeError(
                    "uv not found. Please install uv."
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError("pywrangler version check timed out")


    def _generate_wrangler_toml(self, worker_name: str, package_dir: str, language: str, account_id: str, benchmark_name: Optional[str] = None, code_package: Optional[Benchmark] = None, container_deployment: bool = False, container_uri: str = "") -> str:
        """
        Generate a wrangler.toml configuration file for the worker.

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
        # Container deployment configuration
        if container_deployment:
            # Containers ALWAYS use Node.js worker.js for orchestration (@cloudflare/containers is Node.js only)
            # The container itself can run any language (Python, Node.js, etc.)
            # R2 and NoSQL access is proxied through worker.js which has the bindings
            
            # Determine if this benchmark needs larger disk space
            # 411.image-recognition needs more disk for PyTorch models
            # 311.compression needs more disk for file compression operations
            # 504.dna-visualisation needs more disk for DNA sequence processing
            # Python containers need even more space due to zip file creation doubling disk usage
            instance_type = ""
            if benchmark_name and ("411.image-recognition" in benchmark_name or "311.compression" in benchmark_name or "504.dna-visualisation" in benchmark_name):
                # Use "standard" (largest) for Python, "standard-4" for Node.js
                # if language == "python":
                #     instance_type = '\ninstance_type = "standard-4"  # Largest available - needed for Python zip operations\n'
                # else:
                instance_type = '\ninstance_type = "standard-4"  # 20GB Disk, 12GB Memory\n'
            
            toml_content = f"""name = "{worker_name}"
main = "worker.js"
compatibility_date = "2025-11-18"
account_id = "{account_id}"
compatibility_flags = ["nodejs_compat"]

[observability]
enabled = true

[[containers]]
max_instances = 10
class_name = "ContainerWorker"
image = "./Dockerfile"{instance_type}

# Durable Object binding for Container class (required by @cloudflare/containers)
[[durable_objects.bindings]]
name = "CONTAINER_WORKER"
class_name = "ContainerWorker"

"""
            # Add nosql table bindings if benchmark uses them
            if code_package and code_package.uses_nosql:
                # Get registered nosql tables for this benchmark
                nosql_storage = self.system_resources.get_nosql_storage()
                if nosql_storage.retrieve_cache(benchmark_name):
                    nosql_tables = nosql_storage._tables.get(benchmark_name, {})
                    for table_name in nosql_tables.keys():
                        toml_content += f"""[[durable_objects.bindings]]
name = "{table_name}"
class_name = "KVApiObject"

"""
                        self.logging.info(f"Added Durable Object binding for nosql table '{table_name}'")
                
                # Add migrations for both ContainerWorker and KVApiObject
                # Both need new_sqlite_classes (Container requires SQLite DO backend)
                toml_content += """[[migrations]]
tag = "v1"
new_sqlite_classes = ["ContainerWorker", "KVApiObject"]

"""
            else:
                # Container without nosql - only ContainerWorker migration
                toml_content += """[[migrations]]
tag = "v1"
new_sqlite_classes = ["ContainerWorker"]

"""
        else:
            # Native worker configuration
            main_file = "dist/handler.js" if language == "nodejs" else "handler.py"

            # Build wrangler.toml content
            toml_content = f"""name = "{worker_name}"
main = "{main_file}"
compatibility_date = "2025-11-18"
account_id = "{account_id}"
"""

            if language == "nodejs":
                toml_content += """# Use nodejs_compat for Node.js built-in support
compatibility_flags = ["nodejs_compat"]
no_bundle = true

[build]
command = "node build.js"

[[rules]]
type = "ESModule"
globs = ["**/*.js"]
fallthrough = true

[[rules]]
type = "Text"
globs = ["**/*.html"]
fallthrough = true

"""
            elif language == "python":
                toml_content += """# Enable Python Workers runtime
compatibility_flags = ["python_workers"]
"""

            toml_content += """
[[durable_objects.bindings]]
name = "DURABLE_STORE"
class_name = "KVApiObject"

[[migrations]]
tag = "v3"
new_classes = ["KVApiObject"]
"""


        # Add environment variables (for both native and container deployments)
        vars_content = ""
        if benchmark_name:
            vars_content += f'BENCHMARK_NAME = "{benchmark_name}"\n'

        # Add nosql configuration if benchmark uses it
        if code_package and code_package.uses_nosql:
            vars_content += 'NOSQL_STORAGE_DATABASE = "durable_objects"\n'

        if vars_content:
            toml_content += f"""# Environment variables
[vars]
{vars_content}
"""

        # Add R2 bucket binding for benchmarking files (for both native and container deployments)
        r2_bucket_configured = False
        try:
            storage = self.system_resources.get_storage()
            bucket_name = storage.get_bucket(Resources.StorageBucketType.BENCHMARKS)
            if bucket_name:
                toml_content += f"""# R2 bucket binding for benchmarking files
# This bucket is used by fs and path polyfills to read benchmark data
[[r2_buckets]]
binding = "R2"
bucket_name = "{bucket_name}"

"""
                r2_bucket_configured = True
                self.logging.info(f"R2 bucket '{bucket_name}' will be bound to worker as 'R2'")
        except Exception as e:
            self.logging.warning(
                f"R2 bucket binding not configured: {e}. "
                f"Benchmarks requiring file access will not work properly."
            )


        # Write wrangler.toml to package directory
        toml_path = os.path.join(package_dir, "wrangler.toml")
        with open(toml_path, 'w') as f:
            f.write(toml_content)

        self.logging.info(f"Generated wrangler.toml at {toml_path}")
        return toml_path

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
        Package code for Cloudflare Workers deployment using Wrangler.

        Uses Wrangler CLI to bundle dependencies and prepare for deployment.

        Args:
            directory: Path to the code directory
            language_name: Programming language name
            language_version: Programming language version
            architecture: Target architecture (not used for Workers)
            benchmark: Benchmark name
            is_cached: Whether the code is cached
            container_deployment: Whether to deploy as container

        Returns:
            Tuple of (package_path, package_size, container_uri)
        """
        # Container deployment flow - build Docker image
        if container_deployment:
            self.logging.info(f"Building container image for {benchmark}")
            return self._package_code_container(
                directory, language_name, language_version, architecture, benchmark
            )
        
        # Native worker deployment flow (existing logic)
        return self._package_code_native(
            directory, language_name, language_version, benchmark, is_cached
        )


    def _package_code_native(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int, str]:
        """Package code for native Cloudflare Workers deployment."""

        # Install dependencies
        if language_name == "nodejs":
            # Ensure Wrangler is installed
            self._ensure_wrangler_installed()

            package_file = os.path.join(directory, "package.json")
            node_modules = os.path.join(directory, "node_modules")

            # Only install if package.json exists and node_modules doesn't
            if os.path.exists(package_file) and not os.path.exists(node_modules):
                self.logging.info(f"Installing Node.js dependencies in {directory}")
                try:
                    # Install production dependencies
                    result = subprocess.run(
                        ["npm", "install"],
                        cwd=directory,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=120
                    )
                    self.logging.info("npm install completed successfully")
                    if result.stdout:
                        self.logging.debug(f"npm output: {result.stdout}")

                    # Install esbuild as a dev dependency (needed by build.js)
                    self.logging.info("Installing esbuild for custom build script...")
                    result = subprocess.run(
                        ["npm", "install", "--save-dev", "esbuild"],
                        cwd=directory,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=60
                    )
                    self.logging.info("esbuild installed successfully")


                except subprocess.TimeoutExpired:
                    self.logging.error("npm install timed out")
                    raise RuntimeError("Failed to install Node.js dependencies: timeout")
                except subprocess.CalledProcessError as e:
                    self.logging.error(f"npm install failed: {e.stderr}")
                    raise RuntimeError(f"Failed to install Node.js dependencies: {e.stderr}")
                except FileNotFoundError:
                    raise RuntimeError(
                        "npm not found. Please install Node.js and npm to deploy Node.js benchmarks."
                    )
            elif os.path.exists(node_modules):
                self.logging.info(f"Node.js dependencies already installed in {directory}")

                # Ensure esbuild is available even for cached installations
                esbuild_path = os.path.join(node_modules, "esbuild")
                if not os.path.exists(esbuild_path):
                    self.logging.info("Installing esbuild for custom build script...")
                    try:
                        subprocess.run(
                            ["npm", "install", "--save-dev", "esbuild"],
                            cwd=directory,
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=60
                        )
                        self.logging.info("esbuild installed successfully")
                    except Exception as e:
                        self.logging.warning(f"Failed to install esbuild: {e}")

        elif language_name == "python":
            # Ensure Wrangler is installed
            self._ensure_pywrangler_installed()

            requirements_file = os.path.join(directory, "requirements.txt")
            if os.path.exists(f"{requirements_file}.{language_version}"):
                src = f"{requirements_file}.{language_version}"
                dest = requirements_file
                shutil.move(src, dest)
                self.logging.info(f"move {src} to {dest}")



            # move function_cloudflare.py into function.py
            function_cloudflare_file = os.path.join(directory, "function_cloudflare.py")
            if os.path.exists(function_cloudflare_file):
                src = function_cloudflare_file
                dest = os.path.join(directory, "function.py")
                shutil.move(src, dest)
                self.logging.info(f"move {src} to {dest}")

            if os.path.exists(requirements_file):
                with open(requirements_file, 'r') as reqf:
                    reqtext = reqf.read()
                supported_pkg = \
['affine', 'aiohappyeyeballs', 'aiohttp', 'aiosignal', 'altair', 'annotated-types',\
'anyio', 'apsw', 'argon2-cffi', 'argon2-cffi-bindings', 'asciitree', 'astropy', 'astropy_iers_data',\
'asttokens', 'async-timeout', 'atomicwrites', 'attrs', 'audioop-lts', 'autograd', 'awkward-cpp', 'b2d',\
'bcrypt', 'beautifulsoup4', 'bilby.cython', 'biopython', 'bitarray', 'bitstring', 'bleach', 'blosc2', 'bokeh',\
'boost-histogram', 'brotli', 'cachetools', 'casadi', 'cbor-diag', 'certifi', 'cffi', 'cffi_example', 'cftime',\
'charset-normalizer', 'clarabel', 'click', 'cligj', 'clingo', 'cloudpickle', 'cmyt', 'cobs', 'colorspacious',\
'contourpy', 'coolprop', 'coverage', 'cramjam', 'crc32c', 'cryptography', 'css-inline', 'cssselect', 'cvxpy-base', 'cycler',\
'cysignals', 'cytoolz', 'decorator', 'demes', 'deprecation', 'diskcache', 'distlib', 'distro', 'docutils', 'donfig',\
'ewah_bool_utils', 'exceptiongroup', 'executing', 'fastapi', 'fastcan', 'fastparquet', 'fiona', 'fonttools', 'freesasa',\
'frozenlist', 'fsspec', 'future', 'galpy', 'gmpy2', 'gsw', 'h11', 'h3', 'h5py', 'highspy', 'html5lib', 'httpcore',\
'httpx', 'idna', 'igraph', 'imageio', 'imgui-bundle', 'iminuit', 'iniconfig', 'inspice', 'ipython', 'jedi', 'Jinja2',\
'jiter', 'joblib', 'jsonpatch', 'jsonpointer', 'jsonschema', 'jsonschema_specifications', 'kiwisolver',\
'lakers-python', 'lazy_loader', 'lazy-object-proxy', 'libcst', 'lightgbm', 'logbook', 'lxml', 'lz4', 'MarkupSafe',\
'matplotlib', 'matplotlib-inline', 'memory-allocator', 'micropip', 'mmh3', 'more-itertools', 'mpmath',\
'msgpack', 'msgspec', 'msprime', 'multidict', 'munch', 'mypy', 'narwhals', 'ndindex', 'netcdf4', 'networkx',\
'newick', 'nh3', 'nlopt', 'nltk', 'numcodecs', 'numpy', 'openai', 'opencv-python', 'optlang', 'orjson',\
'packaging', 'pandas', 'parso', 'patsy', 'pcodec', 'peewee', 'pi-heif', 'Pillow', 'pillow-heif', 'pkgconfig',\
'platformdirs', 'pluggy', 'ply', 'pplpy', 'primecountpy', 'prompt_toolkit', 'propcache', 'protobuf', 'pure-eval',\
'py', 'pyclipper', 'pycparser', 'pycryptodome', 'pydantic', 'pydantic_core', 'pyerfa', 'pygame-ce', 'Pygments',\
'pyheif', 'pyiceberg', 'pyinstrument', 'pylimer-tools', 'PyMuPDF', 'pynacl', 'pyodide-http', 'pyodide-unix-timezones',\
'pyparsing', 'pyrsistent', 'pysam', 'pyshp', 'pytaglib', 'pytest', 'pytest-asyncio', 'pytest-benchmark', 'pytest_httpx',\
'python-calamine', 'python-dateutil', 'python-flint', 'python-magic', 'python-sat', 'python-solvespace', 'pytz', 'pywavelets',\
'pyxel', 'pyxirr', 'pyyaml', 'rasterio', 'rateslib', 'rebound', 'reboundx', 'referencing', 'regex', 'requests',\
'retrying', 'rich', 'river', 'RobotRaconteur', 'rpds-py', 'ruamel.yaml', 'rustworkx', 'scikit-image', 'scikit-learn',\
'scipy', 'screed', 'setuptools', 'shapely', 'simplejson', 'sisl', 'six', 'smart-open', 'sniffio', 'sortedcontainers',\
'soundfile', 'soupsieve', 'sourmash', 'soxr', 'sparseqr', 'sqlalchemy', 'stack-data', 'starlette', 'statsmodels', 'strictyaml',\
'svgwrite', 'swiglpk', 'sympy', 'tblib', 'termcolor', 'texttable', 'texture2ddecoder', 'threadpoolctl', 'tiktoken', 'tomli',\
'tomli-w', 'toolz', 'tqdm', 'traitlets', 'traits', 'tree-sitter', 'tree-sitter-go', 'tree-sitter-java', 'tree-sitter-python',\
'tskit', 'typing-extensions', 'tzdata', 'ujson', 'uncertainties', 'unyt', 'urllib3', 'vega-datasets', 'vrplib', 'wcwidth',\
'webencodings', 'wordcloud', 'wrapt', 'xarray', 'xgboost', 'xlrd', 'xxhash', 'xyzservices', 'yarl', 'yt', 'zengl', 'zfpy', 'zstandard']
                needed_pkg = []
                for pkg in supported_pkg:
                    if pkg.lower() in reqtext.lower():
                        needed_pkg.append(pkg)

                project_file = os.path.join(directory, "pyproject.toml")
                depstr = str(needed_pkg).replace("\'", "\"")
                with open(project_file, 'w') as pf:
                    pf.write(f"""
[project]
name = "{benchmark.replace(".", "-")}-python-{language_version.replace(".", "")}"
version = "0.1.0"
description = "dummy description"
requires-python = ">={language_version}"
dependencies = {depstr}

[dependency-groups]
dev = [
  "workers-py",
  "workers-runtime-sdk"
]
                    """)
            # move into function dir
            funcdir = os.path.join(directory, "function")
            if not os.path.exists(funcdir):
                os.makedirs(funcdir)

            dont_move = ["handler.py", "function", "python_modules", "pyproject.toml"]
            for thing in os.listdir(directory):
                if thing not in dont_move:
                    src = os.path.join(directory, thing)
                    dest = os.path.join(directory, "function", thing)
                    shutil.move(src, dest)
                    self.logging.info(f"move {src} to {dest}")

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

    def _package_code_container(
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
            import re
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
        
        # For Python containers, fix relative imports in benchmark code
        # Containers use flat structure, so "from . import storage" must become "import storage"
        if language_name == "python":
            for item in os.listdir(directory):
                if item.endswith('.py') and item not in ['handler.py', 'storage.py', 'nosql.py', 'worker.py']:
                    filepath = os.path.join(directory, item)
                    with open(filepath, 'r') as f:
                        content = f.read()
                    
                    # Replace relative imports with absolute imports
                    modified = False
                    if 'from . import storage' in content:
                        content = content.replace('from . import storage', 'import storage')
                        modified = True
                    if 'from . import nosql' in content:
                        content = content.replace('from . import nosql', 'import nosql')
                        modified = True
                    
                    if modified:
                        with open(filepath, 'w') as f:
                            f.write(content)
                        self.logging.info(f"Fixed relative imports in {item}")
        
        # For Node.js containers, transform benchmark code to be async-compatible
        # The container wrapper uses async HTTP calls, but benchmarks expect sync
        elif language_name == "nodejs":
            import re
            for item in os.listdir(directory):
                if item.endswith('.js') and item not in ['handler.js', 'storage.js', 'nosql.js', 'worker.js', 'build.js', 'request-polyfill.js']:
                    filepath = os.path.join(directory, item)
                    with open(filepath, 'r') as f:
                        content = f.read()
                    
                    # Only transform if file uses nosqlClient
                    if 'nosqlClient' not in content:
                        continue
                    
                    self.logging.info(f"Transforming {item} for async nosql...")
                    
                    # Step 1: Add await before nosqlClient method calls
                    content = re.sub(
                        r'(\s*)((?:const|let|var)\s+\w+\s*=\s*)?nosqlClient\.(insert|get|update|query|delete)\s*\(',
                        r'\1\2await nosqlClient.\3(',
                        content
                    )
                    
                    # Step 2: Make all function declarations async
                    content = re.sub(r'^(\s*)function\s+(\w+)\s*\(', r'\1async function \2(', content, flags=re.MULTILINE)
                    
                    # Step 3: Add await before user-defined function calls
                    lines = content.split('\n')
                    transformed_lines = []
                    control_flow = {'if', 'for', 'while', 'switch', 'catch', 'return'}
                    builtins = {'console', 'require', 'push', 'join', 'split', 'map', 'filter', 
                               'reduce', 'forEach', 'find', 'findIndex', 'some', 'every', 
                               'includes', 'parseInt', 'parseFloat', 'isNaN', 'Array', 
                               'Object', 'String', 'Number', 'Boolean', 'Math', 'JSON', 
                               'Date', 'RegExp', 'Error', 'Promise'}
                    
                    for line in lines:
                        # Skip function declarations
                        if re.search(r'\bfunction\s+\w+\s*\(', line) or re.search(r'=\s*(async\s+)?function\s*\(', line):
                            transformed_lines.append(line)
                            continue
                        
                        # Add await before likely user-defined function calls
                        def replacer(match):
                            prefix = match.group(1)
                            assignment = match.group(2) or ''
                            func_name = match.group(3)
                            
                            if func_name in control_flow or func_name in builtins:
                                return match.group(0)
                            
                            return f"{prefix}{assignment}await {func_name}("
                        
                        line = re.sub(
                            r'(^|\s+|;|,|\()((?:const|let|var)\s+\w+\s*=\s*)?(\w+)\s*\(',
                            replacer,
                            line
                        )
                        transformed_lines.append(line)
                    
                    content = '\n'.join(transformed_lines)
                    
                    with open(filepath, 'w') as f:
                        f.write(content)
                    self.logging.info(f"Transformed {item} for async nosql")
        
        # Install dependencies for container orchestration
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
                    # Merge benchmark dependencies with worker dependencies
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
            self.logging.info("Created package.json for Python container worker.js orchestration")
        
        # Install Node.js dependencies (needed for all containers for worker.js)
        self.logging.info(f"Installing @cloudflare/containers for worker.js orchestration in {directory}")
        try:
            result = subprocess.run(
                ["npm", "install", "--production"],
                cwd=directory,
                capture_output=True,
                text=True,
                check=True,
                timeout=120
            )
            self.logging.info("npm install completed successfully")
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
                import re
                modified = False
                if 'download.pytorch.org/whl' in content:
                    # Remove direct wheel URLs and replace with proper torch installation
                    lines = content.split('\n')
                    new_lines = []
                    for line in lines:
                        if 'download.pytorch.org/whl/cpu/torch-' in line:
                            # Extract version from URL (e.g., torch-2.0.0+cpu)
                            match = re.search(r'torch-([0-9.]+)(?:%2B|\+)cpu', line)
                            if match:
                                version = match.group(1)
                                # Use index-url method instead of direct wheel
                                new_lines.append(f'torch=={version}')
                                modified = True
                            else:
                                new_lines.append(line)
                        else:
                            new_lines.append(line)
                    
                    if modified:
                        # Add extra-index-url at the top for CPU-only torch
                        content = '--extra-index-url https://download.pytorch.org/whl/cpu\n' + '\n'.join(new_lines)
                        with open(requirements_file, 'w') as f:
                            f.write(content)
                        self.logging.info("Modified requirements.txt to use torch index-url instead of direct wheels")
                
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
            # Build the Docker image locally (no push)
            # Use --no-cache to ensure handler changes are picked up
            # Note: BASE_IMAGE is already set in the Dockerfile, no need to pass as build arg
            result = subprocess.run(
                ["docker", "build", "--no-cache", "-t", image_tag, "."],
                cwd=directory,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minutes for build
            )
            
            self.logging.info(f"Local container image built: {image_tag}")
            if result.stdout:
                self.logging.debug(f"Docker build output: {result.stdout}")
            
            return image_tag
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Docker build failed for {image_tag}"
            if e.stderr:
                error_msg += f": {e.stderr}"
            self.logging.error(error_msg)
            raise RuntimeError(error_msg)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Docker build timed out for {image_tag}")

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
        package = code_package.code_location
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

        # Add LibraryTrigger and HTTPTrigger
        from sebs.cloudflare.triggers import LibraryTrigger, HTTPTrigger

        library_trigger = LibraryTrigger(func_name, self)
        library_trigger.logging_handlers = self.logging_handlers
        worker.add_trigger(library_trigger)

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
        """Create or update a Cloudflare Worker using Wrangler CLI.

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
        # Generate wrangler.toml for this worker
        self._generate_wrangler_toml(worker_name, package_dir, language, account_id, benchmark_name, code_package, container_deployment, container_uri)

        # Set up environment for Wrangler
        env = os.environ.copy()
        
        # Add uv tools bin directory to PATH for pywrangler access
        home_dir = os.path.expanduser("~")
        uv_bin_dir = os.path.join(home_dir, ".local", "share", "uv", "tools", "workers-py", "bin")
        if os.path.exists(uv_bin_dir):
            env['PATH'] = f"{uv_bin_dir}:{env.get('PATH', '')}"
        
        if self.config.credentials.api_token:
            env['CLOUDFLARE_API_TOKEN'] = self.config.credentials.api_token
        elif self.config.credentials.email and self.config.credentials.api_key:
            env['CLOUDFLARE_EMAIL'] = self.config.credentials.email
            env['CLOUDFLARE_API_KEY'] = self.config.credentials.api_key

        env['CLOUDFLARE_ACCOUNT_ID'] = account_id

        # Deploy using Wrangler
        self.logging.info(f"Deploying worker {worker_name} using Wrangler...")

        # For container deployments, always use wrangler (not pywrangler)
        # For native deployments, use wrangler for nodejs, pywrangler for python
        if container_deployment:
            wrangler_cmd = "wrangler"
        else:
            wrangler_cmd = "wrangler" if language == "nodejs" else "pywrangler"

        try:
            # Increase timeout for large container images (e.g., 411.image-recognition with PyTorch)
            # Container deployment requires pushing large images to Cloudflare
            deploy_timeout = 1200 if container_deployment else 180  # 20 minutes for containers, 3 for native
            
            result = subprocess.run(
                [wrangler_cmd, "deploy"],
                cwd=package_dir,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=deploy_timeout
            )

            self.logging.info(f"Worker {worker_name} deployed successfully")
            if result.stdout:
                self.logging.debug(f"Wrangler deploy output: {result.stdout}")

            # For container deployments, wait for Durable Object infrastructure to initialize
            # The container binding needs time to propagate before first invocation
            if container_deployment:
                self.logging.info("Waiting for container Durable Object to initialize...")
                self._wait_for_durable_object_ready(worker_name, package_dir, env)
            
            # for benchmarks 220, 311, 411 we need to wait longer after deployment
            # if benchmark_name in ["220.video-processing", "311.compression", "411.image-recognition", "504.dna-visualisation"]:
            #     self.logging.info("Waiting 120 seconds for benchmark initialization...")
            #     time.sleep(400)

            # For container deployments, wait for Durable Object infrastructure to initialize
            # The container binding needs time to propagate before first invocation
            if container_deployment:
                self.logging.info("Waiting 60 seconds for container Durable Object to initialize...")
                time.sleep(60)

            # Parse the output to get worker URL
            # Wrangler typically outputs: "Published <worker-name> (<version>)"
            # and "https://<worker-name>.<subdomain>.workers.dev"

            return {"success": True, "output": result.stdout}

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Wrangler deployment timed out for worker {worker_name}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Wrangler deployment failed for worker {worker_name}"
            if e.stderr:
                error_msg += f": {e.stderr}"
            self.logging.error(error_msg)
            raise RuntimeError(error_msg)

    def _wait_for_durable_object_ready(self, worker_name: str, package_dir: str, env: dict):
        """Wait for container Durable Object to be fully provisioned and ready."""
        max_wait_seconds = 400
        wait_interval = 10
        start_time = time.time()
        
        account_id = env.get('CLOUDFLARE_ACCOUNT_ID')
        worker_url = self._build_workers_dev_url(worker_name, account_id)
        
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
                
                # 503 = not ready yet (expected, keep waiting)
                elif response.status_code == 503:
                    elapsed = int(time.time() - start_time)
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('error', 'Container provisioning')
                        self.logging.info(f"{error_msg}... ({elapsed}s elapsed)")
                    except:
                        self.logging.info(f"Container provisioning... ({elapsed}s elapsed)")
                    consecutive_failures = 0  # This is expected
                
                # 500 or other = something's wrong
                else:
                    consecutive_failures += 1
                    self.logging.warning(f"Unexpected status {response.status_code}: {response.text[:200]}")
                    
                    # If we get too many unexpected errors, something might be broken
                    if consecutive_failures >= max_consecutive_failures:
                        self.logging.error(f"Got {consecutive_failures} consecutive errors, container may be broken")
                        return False
                    
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

    def _get_workers_dev_subdomain(self, account_id: str) -> Optional[str]:
        """Fetch the workers.dev subdomain for the given account.

        Cloudflare exposes an endpoint that returns the account-level workers
        subdomain (the readable name used in *.workers.dev), e.g.
        GET /accounts/{account_id}/workers/subdomain

        Returns the subdomain string (e.g. 'marcin-copik') or None on failure.
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
            if sub:
                return f"https://{worker_name}.{sub}.workers.dev"
            else:
                # fallback: some code historically used account_id in the host
                self.logging.warning(
                    "Using account ID in workers.dev URL as a fallback. "
                    "Enable the workers.dev subdomain in Cloudflare for proper URLs."
                )
                return f"https://{worker_name}.{account_id}.workers.dev"
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
            container_deployment: Whether to deploy as container
            container_uri: URI of container image
        """
        worker = cast(CloudflareWorker, function)
        package = code_package.code_location
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
        from sebs.cloudflare.triggers import LibraryTrigger, HTTPTrigger

        worker = cast(CloudflareWorker, function)

        if trigger_type == Trigger.TriggerType.LIBRARY:
            trigger = LibraryTrigger(worker.name, self)
            trigger.logging_handlers = self.logging_handlers
            return trigger
        elif trigger_type == Trigger.TriggerType.HTTP:
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

        Saves configuration to cache.
        """
        try:
            self.cache_client.lock()
            self.config.update_cache(self.cache_client)
        finally:
            self.cache_client.unlock()

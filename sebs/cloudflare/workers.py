"""
Cloudflare Workers native deployment implementation.

Handles packaging, deployment, and management of native Cloudflare Workers
(non-container deployments using JavaScript/Python runtime).
"""

import os
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
            "../..", 
            "templates", 
            "wrangler-worker.toml"
        )
        with open(template_path, 'rb') as f:
            config = tomllib.load(f)
        
        # Update basic configuration
        config['name'] = worker_name
        config['main'] = "dist/handler.js" if language == "nodejs" else "handler.py"
        config['account_id'] = account_id
        
        # Add language-specific configuration
        if language == "nodejs":
            config['compatibility_flags'] = ["nodejs_compat"]
            config['no_bundle'] = True
            config['build'] = {'command': 'node build.js'}
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
            config['compatibility_flags'] = ["python_workers"]
        
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
        benchmark: str,
        is_cached: bool,
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
        # Install dependencies
        if language_name == "nodejs":
            package_file = os.path.join(directory, "package.json")
            node_modules = os.path.join(directory, "node_modules")

            # Only install if package.json exists and node_modules doesn't
            if os.path.exists(package_file) and not os.path.exists(node_modules):
                self.logging.info(f"Installing Node.js dependencies in {directory}")
                # Use CLI container for npm install - no Node.js/npm needed on host
                cli = self._get_cli()
                container_path = f"/tmp/npm_install/{os.path.basename(directory)}"
                
                try:
                    # Upload package directory to container
                    cli.upload_package(directory, container_path)
                    
                    # Install production dependencies
                    self.logging.info("Installing npm dependencies in container...")
                    output = cli.npm_install(container_path)
                    self.logging.info("npm install completed successfully")
                    self.logging.debug(f"npm output: {output}")

                    # Install esbuild as a dev dependency (needed by build.js)
                    self.logging.info("Installing esbuild for custom build script...")
                    cli.execute(f"cd {container_path} && npm install --save-dev esbuild")
                    self.logging.info("esbuild installed successfully")
                    
                    # Download node_modules back to host
                    bits, stat = cli.docker_instance.get_archive(f"{container_path}/node_modules")
                    file_obj = io.BytesIO()
                    for chunk in bits:
                        file_obj.write(chunk)
                    file_obj.seek(0)
                    with tarfile.open(fileobj=file_obj) as tar:
                        tar.extractall(directory)
                    
                    self.logging.info(f"Downloaded node_modules to {directory}")

                except Exception as e:
                    self.logging.error(f"npm install in container failed: {e}")
                    raise RuntimeError(f"Failed to install Node.js dependencies: {e}")
            elif os.path.exists(node_modules):
                self.logging.info(f"Node.js dependencies already installed in {directory}")

                # Ensure esbuild is available even for cached installations
                esbuild_path = os.path.join(node_modules, "esbuild")
                if not os.path.exists(esbuild_path):
                    self.logging.info("Installing esbuild for custom build script...")
                    cli = self._get_cli()
                    container_path = f"/tmp/npm_install/{os.path.basename(directory)}"
                    
                    try:
                        cli.upload_package(directory, container_path)
                        cli.execute(f"cd {container_path} && npm install --save-dev esbuild")
                        
                        # Download node_modules back to host
                        bits, stat = cli.docker_instance.get_archive(f"{container_path}/node_modules")
                        file_obj = io.BytesIO()
                        for chunk in bits:
                            file_obj.write(chunk)
                        file_obj.seek(0)
                        with tarfile.open(fileobj=file_obj) as tar:
                            tar.extractall(directory)
                        
                        self.logging.info("esbuild installed successfully")
                    except Exception as e:
                        self.logging.error(f"Failed to install esbuild: {e}")
                        raise RuntimeError(f"Failed to install esbuild: {e}")

        elif language_name == "python":
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

    def shutdown(self):
        """Shutdown CLI container if initialized."""
        if self._cli is not None:
            self._cli.shutdown()
            self._cli = None

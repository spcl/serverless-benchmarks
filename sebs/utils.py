"""
Utility functions and classes for the Serverless Benchmarking Suite (SeBs).

This module provides common utilities used throughout the framework, including:
- File system operations and path management
- Process execution and command handling
- JSON serialization and data manipulation
- Logging configuration and utilities
- Platform detection functions
"""

import json
import logging
import os
import shutil
import subprocess
import uuid
import click
import datetime
import platform

from typing import List, Optional

# Global constants
PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
DOCKER_DIR = os.path.join(PROJECT_DIR, "dockerfiles")
PACK_CODE_APP = "pack_code_{}.sh"


def project_absolute_path(*paths: str) -> str:
    """
    Join paths relative to the project root directory.
    
    Args:
        *paths: Path components to join
        
    Returns:
        str: Absolute path including the project directory
    """
    return os.path.join(PROJECT_DIR, *paths)


class JSONSerializer(json.JSONEncoder):
    """
    Custom JSON encoder for objects with serialize method.
    
    This encoder handles objects by:
    1. Using their serialize() method if available
    2. Converting dictionaries to strings
    3. Using vars() to get object attributes
    4. Falling back to string representation
    """
    def default(self, o):
        """
        Custom serialization for objects.
        
        Args:
            o: Object to serialize
            
        Returns:
            JSON serializable representation of the object
        """
        if hasattr(o, "serialize"):
            return o.serialize()
        elif isinstance(o, dict):
            return str(o)
        else:
            try:
                return vars(o)
            except TypeError:
                return str(o)


def serialize(obj) -> str:
    """
    Serialize an object to a JSON string.
    
    Args:
        obj: Object to serialize
        
    Returns:
        str: JSON string representation of the object
    """
    if hasattr(obj, "serialize"):
        return json.dumps(obj.serialize(), sort_keys=True, indent=2)
    else:
        return json.dumps(obj, cls=JSONSerializer, sort_keys=True, indent=2)


def execute(cmd, shell=False, cwd=None) -> str:
    """
    Execute a shell command and capture its output, handling errors.
    
    Args:
        cmd: Command to execute (string)
        shell: Whether to use shell execution (enables wildcards, pipes, etc.)
        cwd: Working directory for command execution
        
    Returns:
        str: Command output as string
        
    Raises:
        RuntimeError: If command execution fails
    """
    if not shell:
        cmd = cmd.split()
    ret = subprocess.run(
        cmd, shell=shell, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if ret.returncode:
        raise RuntimeError(
            "Running {} failed!\n Output: {}".format(cmd, ret.stdout.decode("utf-8"))
        )
    return ret.stdout.decode("utf-8")


def update_nested_dict(cfg: dict, keys: List[str], value: Optional[str]) -> None:
    """
    Update a nested dictionary with a value at the specified key path.
    
    Args:
        cfg: Dictionary to update
        keys: List of keys forming a path to the value
        value: Value to set (skipped if None)
    """
    if value is not None:
        # make sure parent keys exist
        for key in keys[:-1]:
            cfg = cfg.setdefault(key, {})
        cfg[keys[-1]] = value


def append_nested_dict(cfg: dict, keys: List[str], value: Optional[dict]) -> None:
    """
    Append a dictionary to a nested location in another dictionary.
    
    Args:
        cfg: Dictionary to update
        keys: List of keys forming a path to the value
        value: Dictionary to append (skipped if None or empty)
    """
    if value:
        # make sure parent keys exist
        for key in keys[:-1]:
            cfg = cfg.setdefault(key, {})
        cfg[keys[-1]] = {**cfg[keys[-1]], **value}


def find(name: str, path: str) -> Optional[str]:
    """
    Find a directory with the given name in the specified path.
    
    Args:
        name: Directory name to find
        path: Path to search in
        
    Returns:
        str: Path to the found directory, or None if not found
    """
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None


def create_output(directory: str, preserve_dir: bool, verbose: bool) -> str:
    """
    Create or clean an output directory for benchmark results.
    
    Args:
        directory: Path to create
        preserve_dir: Whether to preserve existing directory
        verbose: Verbosity level for logging
        
    Returns:
        str: Absolute path to the output directory
    """
    output_dir = os.path.abspath(directory)
    if os.path.exists(output_dir) and not preserve_dir:
        shutil.rmtree(output_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    configure_logging()

    return output_dir


def configure_logging() -> None:
    """
    Configure global logging settings.
    
    Reduces noise from third-party libraries by setting their log levels to ERROR.
    This ensures that only important messages from these libraries are shown.
    """
    # disable information from libraries logging to decrease output noise
    loggers = ["urrlib3", "docker", "botocore"]
    for name in logging.root.manager.loggerDict:
        for logger in loggers:
            if name.startswith(logger):
                logging.getLogger(name).setLevel(logging.ERROR)


def find_benchmark(benchmark: str, path: str) -> Optional[str]:
    """
    Locate directory corresponding to a benchmark in the repository.
    
    Searches for a benchmark directory in either the benchmarks or 
    benchmarks-data directories.
    
    Args:
        benchmark: Benchmark name
        path: Path for lookup, relative to repository (usually 'benchmarks' or 'benchmarks-data')
        
    Returns:
        str: Path to benchmark directory, or None if not found
    """
    benchmarks_dir = os.path.join(PROJECT_DIR, path)
    benchmark_path = find(benchmark, benchmarks_dir)
    return benchmark_path


def global_logging() -> None:
    """
    Set up basic global logging configuration.
    
    Configures the root logger with a standard format, timestamp, and INFO level.
    This provides a baseline for all logging in the application.
    """
    logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s"
    logging_date_format = "%H:%M:%S"
    logging.basicConfig(format=logging_format, datefmt=logging_date_format, level=logging.INFO)


class ColoredWrapper:
    """
    Wrapper for logging with colored console output.
    
    This class provides formatted, colorized logging output for better readability
    in terminal environments. It optionally propagates messages to the standard
    Python logger.
    
    Attributes:
        SUCCESS: Green color code for success messages
        STATUS: Blue color code for status/info messages
        WARNING: Yellow color code for warnings
        ERROR: Red color code for errors
        BOLD: Bold text formatting code
        END: Code to reset text formatting
    """
    SUCCESS = "\033[92m"
    STATUS = "\033[94m"
    WARNING = "\033[93m"
    ERROR = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"

    def __init__(self, prefix, logger, verbose=True, propagte=False):
        """
        Initialize the colored logging wrapper.
        
        Args:
            prefix: Prefix for log messages (usually class name)
            logger: Python logger to propagate to
            verbose: Whether to show debug messages
            propagte: Whether to propagate messages to the Python logger
        """
        self.verbose = verbose
        self.propagte = propagte
        self.prefix = prefix
        self._logging = logger

    def debug(self, message):
        """
        Log a debug message.
        
        Args:
            message: The message to log
        """
        if self.verbose:
            self._print(message, ColoredWrapper.STATUS)
            if self.propagte:
                self._logging.debug(message)

    def info(self, message):
        """
        Log an informational message.
        
        Args:
            message: The message to log
        """
        self._print(message, ColoredWrapper.SUCCESS)
        if self.propagte:
            self._logging.info(message)

    def warning(self, message):
        """
        Log a warning message.
        
        Args:
            message: The message to log
        """
        self._print(message, ColoredWrapper.WARNING)
        if self.propagte:
            self._logging.warning(message)

    def error(self, message):
        """
        Log an error message.
        
        Args:
            message: The message to log
        """
        self._print(message, ColoredWrapper.ERROR)
        if self.propagte:
            self._logging.error(message)

    def critical(self, message):
        """
        Log a critical error message.
        
        Args:
            message: The message to log
        """
        self._print(message, ColoredWrapper.ERROR)
        if self.propagte:
            self._logging.critical(message)

    def _print(self, message, color):
        """
        Print a formatted message to the console.
        
        Args:
            message: The message to print
            color: ANSI color code to use
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")
        click.echo(
            f"{color}{ColoredWrapper.BOLD}[{timestamp}]{ColoredWrapper.END} "
            f"{ColoredWrapper.BOLD}{self.prefix}{ColoredWrapper.END} {message}"
        )


class LoggingHandlers:
    """
    Configures and manages logging handlers.
    
    This class sets up handlers for logging to files and tracks verbosity settings
    for use with ColoredWrapper.
    
    Attributes:
        handler: FileHandler for logging to a file
        verbosity: Whether to include debug-level messages
    """
    
    def __init__(self, verbose: bool = False, filename: Optional[str] = None):
        """
        Initialize logging handlers.
        
        Args:
            verbose: Whether to include debug-level messages
            filename: Optional file to log to
        """
        logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s"
        logging_date_format = "%H:%M:%S"
        formatter = logging.Formatter(logging_format, logging_date_format)
        self.handler: Optional[logging.FileHandler] = None

        # Remember verbosity for colored wrapper
        self.verbosity = verbose

        # Add file output if needed
        if filename:
            file_out = logging.FileHandler(filename=filename, mode="w")
            file_out.setFormatter(formatter)
            file_out.setLevel(logging.DEBUG if verbose else logging.INFO)
            self.handler = file_out


class LoggingBase:
    """
    Base class providing consistent logging functionality across the framework.
    
    This class sets up a logger with a unique identifier and provides methods
    for logging at different levels with consistent formatting. It supports
    both console output with color coding and optional file logging.
    
    Attributes:
        log_name: Unique identifier for this logger
        logging: ColoredWrapper for formatted console output
    """
    
    def __init__(self):
        """
        Initialize the logging base with a unique identifier.
        
        Creates a unique name for the logger based on class name and a random ID,
        then configures a standard logger and colored wrapper.
        """
        uuid_name = str(uuid.uuid4())[0:4]
        if hasattr(self, "typename"):
            self.log_name = f"{self.typename()}-{uuid_name}"
        else:
            self.log_name = f"{self.__class__.__name__}-{uuid_name}"

        self._logging = logging.getLogger(self.log_name)
        self._logging.setLevel(logging.INFO)
        self.wrapper = ColoredWrapper(self.log_name, self._logging)

    @property
    def logging(self) -> ColoredWrapper:
        """
        Get the colored logging wrapper.
        
        Returns:
            ColoredWrapper: The logging wrapper for this instance
        """
        # This would always print log with color. And only if
        # filename in LoggingHandlers is set, it would log to file.
        return self.wrapper

    @property
    def logging_handlers(self) -> LoggingHandlers:
        """
        Get the logging handlers configuration.
        
        Returns:
            LoggingHandlers: The current handlers configuration
        """
        return self._logging_handlers

    @logging_handlers.setter
    def logging_handlers(self, handlers: LoggingHandlers):
        """
        Set new logging handlers configuration.
        
        Args:
            handlers: The new handlers configuration to use
        """
        self._logging_handlers = handlers

        self._logging.propagate = False
        self.wrapper = ColoredWrapper(
            self.log_name,
            self._logging,
            verbose=handlers.verbosity,
            propagte=handlers.handler is not None,
        )

        if self._logging_handlers.handler is not None:
            self._logging.addHandler(self._logging_handlers.handler)


def has_platform(name: str) -> bool:
    """
    Check if a specific platform is enabled via environment variable.
    
    Looks for SEBS_WITH_{name} environment variable set to 'true'.
    
    Args:
        name: Platform name to check
        
    Returns:
        bool: True if platform is enabled, False otherwise
    """
    return os.environ.get(f"SEBS_WITH_{name.upper()}", "False").lower() == "true"


def is_linux() -> bool:
    """
    Check if the system is Linux and not Windows Subsystem for Linux.
    
    Returns:
        bool: True if native Linux, False otherwise
    """
    return platform.system() == "Linux" and "microsoft" not in platform.release().lower()


def catch_interrupt() -> None:
    """
    Set up a signal handler to catch interrupt signals (Ctrl+C).
    
    Prints a stack trace and exits when an interrupt is received.
    This helps with debugging by showing the execution context at
    the time of the interruption.
    """
    import signal
    import sys
    import traceback

    def handler(x, y):
        """
        Handle interrupt signal by printing stack trace and exiting.
        
        Args:
            x: Signal number
            y: Frame object
        """
        traceback.print_stack()
        sys.exit(signal.SIGINT)

    signal.signal(signal.SIGINT, handler)

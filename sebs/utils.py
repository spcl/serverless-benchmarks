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

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
"""Absolute path to the SeBS project root directory."""
DOCKER_DIR = os.path.join(PROJECT_DIR, "dockerfiles")
"""Absolute path to the directory containing Dockerfiles."""
PACK_CODE_APP = "pack_code_{}.sh" # Seems unused, consider removal or add docstring if used.
"""Template string for packaging script names, potentially unused."""


def project_absolute_path(*paths: str) -> str:
    """
    Construct an absolute path relative to the SeBS project root directory.

    :param paths: Variable number of path components to join with the project root.
    :return: Absolute path string.
    """
    return os.path.join(PROJECT_DIR, *paths)


class JSONSerializer(json.JSONEncoder):
    """
    Custom JSON encoder for SeBS objects.

    Handles objects that have a `serialize()` method, dictionaries,
    and attempts to convert other objects using `vars()` or `str()`.
    """
    def default(self, o: Any) -> Any:
        """
        Override the default JSON encoding behavior.

        :param o: The object to encode.
        :return: A serializable representation of the object.
        """
        if hasattr(o, "serialize"):
            return o.serialize()
        # elif isinstance(o, dict): # This condition is problematic, as dicts are usually handled by default.
        #    return str(o) # Converting dict to str is generally not desired for JSON.
        #                 # If the intent was to handle specific non-serializable dicts, it needs refinement.
        #                 # For now, commenting out as it might break standard dict serialization.
        else:
            try:
                return vars(o) # For simple objects, their __dict__ might be serializable
            except TypeError:
                return str(o) # Fallback to string representation


def serialize(obj: Any) -> str:
    """
    Serialize an object to a JSON string using the custom `JSONSerializer`.

    If the object has a `serialize()` method, it's called first.

    :param obj: The object to serialize.
    :return: A JSON string representation of the object, pretty-printed with indent 2.
    """
    if hasattr(obj, "serialize"):
        # Assumes obj.serialize() returns a JSON-serializable dictionary or list
        return json.dumps(obj.serialize(), sort_keys=True, indent=2)
    else:
        return json.dumps(obj, cls=JSONSerializer, sort_keys=True, indent=2)


def execute(cmd: str, shell: bool = False, cwd: Optional[str] = None) -> str:
    """
    Execute a shell command.

    Can run the command directly or through the system's shell.
    Captures stdout and stderr, raising a RuntimeError if the command fails.

    :param cmd: The command string to execute.
    :param shell: If True, execute the command through the shell (allows shell features
                  like wildcards, but can be a security risk if `cmd` is from untrusted input).
                  Defaults to False.
    :param cwd: Optional current working directory for the command execution.
    :return: The decoded stdout of the executed command.
    :raises RuntimeError: If the command returns a non-zero exit code.
    """
    if not shell:
        command_list = cmd.split()
    else:
        command_list = cmd # If shell=True, cmd is passed as a string
        
    process_result = subprocess.run(
        command_list, shell=shell, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if process_result.returncode != 0:
        raise RuntimeError(
            f"Running command '{cmd}' failed with exit code {process_result.returncode}!\n"
            f"Output: {process_result.stdout.decode('utf-8', errors='replace')}"
        )
    return process_result.stdout.decode("utf-8", errors='replace')


def update_nested_dict(cfg: dict, keys: List[str], value: Optional[Any]): # Value type changed to Any
    """
    Update a value in a nested dictionary at a path specified by `keys`.

    If `value` is None, the key at the end of the path is not set or modified.
    Parent dictionaries in the path are created if they don't exist.

    :param cfg: The dictionary to update.
    :param keys: A list of strings representing the path to the value.
    :param value: The new value to set. If None, no update is performed for the final key.
    """
    if value is not None:
        current_level = cfg
        for key_part in keys[:-1]: # Iterate through keys to navigate/create path
            current_level = current_level.setdefault(key_part, {})
        current_level[keys[-1]] = value


def append_nested_dict(cfg: dict, keys: List[str], value_dict: Optional[dict]): # Renamed value to value_dict
    """
    Append/merge a dictionary `value_dict` into a nested dictionary `cfg` at `keys`.

    If `value_dict` is provided, its key-value pairs are merged into the dictionary
    found at the specified path. Existing keys at the target location will be
    overwritten by values from `value_dict`.

    :param cfg: The dictionary to update.
    :param keys: A list of strings representing the path to the target dictionary.
    :param value_dict: The dictionary whose items will be merged into the target.
                       If None, no update is performed.
    """
    if value_dict:
        current_level = cfg
        for key_part in keys[:-1]:
            current_level = current_level.setdefault(key_part, {})
        # Ensure the target key exists and is a dictionary before merging
        target_dict = current_level.setdefault(keys[-1], {})
        if isinstance(target_dict, dict):
            target_dict.update(value_dict)
        else:
            # Handle case where target is not a dict (e.g., overwrite or log error)
            current_level[keys[-1]] = value_dict # Overwrites if not a dict


def find(name: str, search_path: str) -> Optional[str]: # Renamed path to search_path
    """
    Find a directory by name within a given search path.

    Performs a recursive walk starting from `search_path`.

    :param name: The name of the directory to find.
    :param search_path: The root path to start the search from.
    :return: The absolute path to the found directory, or None if not found.
    """
    for root, dirs, _ in os.walk(search_path): # files variable is not used
        if name in dirs:
            return os.path.join(root, name)
    return None


def create_output(directory: str, preserve_dir: bool, verbose: bool) -> str: # verbose seems unused here
    """
    Create or clean an output directory and configure logging.

    If `preserve_dir` is False and the directory exists, it's removed first.
    The directory is then created if it doesn't exist.
    Calls `configure_logging()` (which currently mutes library loggers).

    :param directory: Path to the output directory.
    :param preserve_dir: If True, do not remove the directory if it exists.
    :param verbose: Verbosity flag (passed to logging config, though current configure_logging is simple).
    :return: The absolute path to the created/ensured output directory.
    """
    abs_output_dir = os.path.abspath(directory)
    if os.path.exists(abs_output_dir) and not preserve_dir:
        logging.info(f"Removing existing output directory: {abs_output_dir}")
        shutil.rmtree(abs_output_dir)
    if not os.path.exists(abs_output_dir):
        os.makedirs(abs_output_dir, exist_ok=True)
    
    # configure_logging is currently very simple. If it were to use `verbose` or `output_dir`,
    # those would be passed here.
    configure_logging()

    return abs_output_dir


def configure_logging():
    """
    Configure global logging settings for SeBS.

    Currently, this function disables verbose logging from common libraries
    (urllib3, docker, botocore) by setting their log levels to ERROR,
    to reduce output noise during SeBS execution.
    The commented-out section shows a more elaborate potential logging setup.
    """
    # Disable verbose logging from common libraries
    noisy_loggers = ["urllib3", "docker", "botocore"]
    for logger_name_prefix in noisy_loggers:
        # Iterate over all existing loggers to find matches by prefix
        for name in list(logging.root.manager.loggerDict): # Iterate over a copy of keys
            if name.startswith(logger_name_prefix):
                logging.getLogger(name).setLevel(logging.ERROR)


def find_benchmark(benchmark_name: str, benchmarks_root_path: str) -> Optional[str]:
    """
    Locate a benchmark's directory within a given root path.

    Searches for a directory named `benchmark_name` under `benchmarks_root_path`.

    :param benchmark_name: Name of the benchmark directory to find.
    :param benchmarks_root_path: The root path for benchmark lookup (e.g., "benchmarks" or "benchmarks-data"),
                                 relative to the SeBS project directory.
    :return: Absolute path to the benchmark directory if found, otherwise None.
    """
    # Construct absolute path for searching
    search_dir = project_absolute_path(benchmarks_root_path)
    return find(benchmark_name, search_dir) # Use the general `find` utility


def global_logging():
    """
    Set up basic global logging configuration for the SeBS application.

    Configures a default format, date format, and sets the logging level to INFO.
    This is typically called once at the start of the application.
    """
    logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s"
    logging_date_format = "%H:%M:%S"
    logging.basicConfig(format=logging_format, datefmt=logging_date_format, level=logging.INFO)


class ColoredWrapper:
    """
    A wrapper around a standard Python logger to provide colored console output using Click.

    Allows logging messages with different colors based on severity (DEBUG, INFO,
    WARNING, ERROR, CRITICAL). Can also propagate messages to the underlying logger.
    """
    SUCCESS = "\033[92m" #: Green color for success messages.
    STATUS = "\033[94m"  #: Blue color for status/debug messages.
    WARNING = "\033[93m" #: Yellow color for warning messages.
    ERROR = "\033[91m"   #: Red color for error/critical messages.
    BOLD = "\033[1m"     #: Bold text.
    END = "\033[0m"      #: Reset text formatting.

    def __init__(self, prefix: str, logger: logging.Logger, verbose: bool = True, propagate: bool = False): # Renamed propagte
        """
        Initialize the ColoredWrapper.

        :param prefix: A prefix string to prepend to log messages (e.g., class name).
        :param logger: The underlying `logging.Logger` instance.
        :param verbose: If True, DEBUG messages are printed to console. Defaults to True.
        :param propagate: If True, messages are also passed to the underlying logger's handlers.
                          Defaults to False.
        """
        self.verbose = verbose
        self.propagate = propagate # Renamed from propagte
        self.prefix = prefix
        self._logging = logger

    def debug(self, message: str):
        """Log a DEBUG message. Printed to console if verbose is True."""
        if self.verbose:
            self._print(message, ColoredWrapper.STATUS)
        if self.propagate:
            self._logging.debug(message)

    def info(self, message: str):
        """Log an INFO message."""
        self._print(message, ColoredWrapper.SUCCESS)
        if self.propagate:
            self._logging.info(message)

    def warning(self, message: str):
        """Log a WARNING message."""
        self._print(message, ColoredWrapper.WARNING)
        if self.propagate:
            self._logging.warning(message)

    def error(self, message: str):
        """Log an ERROR message."""
        self._print(message, ColoredWrapper.ERROR)
        if self.propagate:
            self._logging.error(message)

    def critical(self, message: str):
        """Log a CRITICAL message."""
        self._print(message, ColoredWrapper.ERROR) # Uses ERROR color for critical
        if self.propagate:
            self._logging.critical(message)

    def _print(self, message: str, color: str):
        """
        Internal method to print a colored and formatted message to the console using Click.

        :param message: The message string.
        :param color: The ANSI color code string.
        """
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3] # Milliseconds
        click.echo(
            f"{color}{ColoredWrapper.BOLD}[{timestamp}]{ColoredWrapper.END} "
            f"{ColoredWrapper.BOLD}{self.prefix}{ColoredWrapper.END} {message}"
        )


class LoggingHandlers:
    """
    Manages logging handlers, specifically a file handler if a filename is provided.

    Attributes:
        verbosity: Boolean indicating if verbose logging is enabled for console.
        handler: Optional `logging.FileHandler` instance if file logging is active.
    """
    def __init__(self, verbose: bool = False, filename: Optional[str] = None):
        """
        Initialize LoggingHandlers.

        Sets up a file handler if `filename` is provided.

        :param verbose: If True, sets DEBUG level for file log, otherwise INFO.
                        Also stored for use by `ColoredWrapper`.
        :param filename: Optional path to a log file. If provided, a file handler
                         is created and configured.
        """
        logging_format = "%(asctime)s,%(msecs)d %(levelname)s %(name)s: %(message)s"
        logging_date_format = "%H:%M:%S"
        formatter = logging.Formatter(logging_format, logging_date_format)
        self.handler: Optional[logging.FileHandler] = None

        self.verbosity = verbose # Store verbosity for ColoredWrapper

        if filename:
            try:
                file_out_handler = logging.FileHandler(filename=filename, mode="w")
                file_out_handler.setFormatter(formatter)
                file_out_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
                self.handler = file_out_handler
            except Exception as e:
                # Fallback to console if file handler fails, but log the error
                print(f"Error setting up file logger for {filename}: {e}. Logging to console only for this handler context.")
                self.handler = None


class LoggingBase:
    """
    Base class providing standardized logging capabilities for SeBS components.

    Initializes a logger with a unique name (class name + UUID4 prefix) and
    a `ColoredWrapper` for console output. Allows attaching `LoggingHandlers`
    to enable file logging.
    """
    def __init__(self):
        """
        Initialize LoggingBase. Sets up a logger and a default ColoredWrapper.
        `logging_handlers` should be set after initialization to enable file logging.
        """
        uuid_prefix = str(uuid.uuid4())[0:4] # Renamed from uuid_name
        class_name = getattr(self, "typename", lambda: self.__class__.__name__)()
        self.log_name = f"{class_name}-{uuid_prefix}"

        self._logging = logging.getLogger(self.log_name)
        # Default level, can be overridden by handlers
        self._logging.setLevel(logging.DEBUG) # Set logger to DEBUG, handlers control output level
        
        # Default wrapper, might be updated when handlers are set
        self.wrapper = ColoredWrapper(self.log_name, self._logging)
        self._logging_handlers: Optional[LoggingHandlers] = None


    @property
    def logging(self) -> ColoredWrapper:
        """
        Access the `ColoredWrapper` instance for colored console logging.
        The wrapper's verbosity and propagation depend on the configured `logging_handlers`.
        """
        return self.wrapper

    @property
    def logging_handlers(self) -> Optional[LoggingHandlers]: # Can be None if not set
        """The `LoggingHandlers` instance associated with this logger."""
        return self._logging_handlers

    @logging_handlers.setter
    def logging_handlers(self, handlers: Optional[LoggingHandlers]): # Allow setting to None
        """
        Set the `LoggingHandlers` for this logger.

        This configures the underlying logger to use the file handler from `handlers`
        (if any) and updates the `ColoredWrapper` verbosity and propagation settings.

        :param handlers: The LoggingHandlers instance, or None to clear handlers.
        """
        # Remove old handler if it exists and is different or new one is None
        if self._logging_handlers and self._logging_handlers.handler:
            if not handlers or self._logging_handlers.handler != handlers.handler:
                self._logging.removeHandler(self._logging_handlers.handler)
        
        self._logging_handlers = handlers
        
        if handlers:
            self.wrapper = ColoredWrapper(
                self.log_name,
                self._logging,
                verbose=handlers.verbosity,
                propagate=handlers.handler is not None, # Propagate if file handler exists
            )
            if handlers.handler:
                self._logging.addHandler(handlers.handler)
                self._logging.propagate = False # Avoid duplicate messages from root logger if file handler is specific
            else:
                # If no file handler, let messages propagate to root/console handlers if any configured there.
                # However, ColoredWrapper handles console output directly via click.echo.
                # So, for console, propagation might not be desired if root also has console.
                # Defaulting to False to rely on ColoredWrapper for console.
                self._logging.propagate = False
        else:
            # Reset to a default wrapper if handlers are removed
            self.wrapper = ColoredWrapper(self.log_name, self._logging)
            self._logging.propagate = True # Allow propagation if no specific handlers


def has_platform(name: str) -> bool:
    """
    Check if a specific FaaS platform is enabled via environment variables.

    Looks for an environment variable `SEBS_WITH_{NAME_UPPERCASE}` and checks
    if its value is "true" (case-insensitive).

    :param name: The short name of the platform (e.g., "aws", "azure").
    :return: True if the platform is enabled, False otherwise.
    """
    return os.environ.get(f"SEBS_WITH_{name.upper()}", "False").lower() == "true"


def is_linux() -> bool:
    """
    Check if the current operating system is Linux and not Windows Subsystem for Linux (WSL).

    :return: True if native Linux, False otherwise (e.g., Windows, macOS, WSL).
    """
    return platform.system() == "Linux" and "microsoft" not in platform.release().lower()


def catch_interrupt():
    """
    Set up a signal handler to catch KeyboardInterrupt (Ctrl+C) and print a stack trace
    before exiting. Useful for debugging hangs or long operations.
    """
    import signal
    import sys
    import traceback

    def custom_interrupt_handler(signum, frame): # Corrected signature
        print("\nKeyboardInterrupt caught!")
        traceback.print_stack(frame)
        sys.exit(1) # Exit with a non-zero code

    signal.signal(signal.SIGINT, custom_interrupt_handler)

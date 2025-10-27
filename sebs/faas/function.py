"""
Function and execution model for the serverless benchmarking framework.

This module defines the core abstractions for serverless functions, including:
- Function class: Represents a deployed serverless function
- Trigger class: Represents invocation mechanisms for functions
- Runtime and FunctionConfig: Configuration parameters for functions
- ExecutionResult and related classes: Data model for capturing measurements

These abstractions provide a unified interface for handling functions across
different FaaS platforms, allowing for consistent deployment, invocation,
and measurement collection.
"""

from __future__ import annotations

import json
import concurrent.futures
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional, Type, TypeVar  # noqa

from sebs.benchmark import Benchmark
from sebs.utils import LoggingBase


class ExecutionTimes:
    """
    Client-side timing measurements for function execution.

    Stores various timing measurements from the client's perspective,
    including total execution time, HTTP connection times, and benchmark
    runtime. All times are reported in microseconds unless otherwise specified.

    Attributes:
        client: Total client-side execution time in microseconds
        client_begin: Timestamp when the request was initiated
        client_end: Timestamp when the response was received
        benchmark: Benchmark execution time in microseconds
        initialization: Function initialization time in microseconds
        http_startup: Time to establish HTTP connection in seconds
        http_first_byte_return: Time to first byte in seconds
    """

    client: int
    client_begin: datetime
    client_end: datetime
    benchmark: int
    initialization: int
    http_startup: int
    http_first_byte_return: int

    def __init__(self):
        """Initialize with default values."""
        self.client = 0
        self.initialization = 0
        self.benchmark = 0

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionTimes":
        """
        Create an ExecutionTimes instance from a dictionary.

        Args:
            cached_obj: Dictionary containing serialized timing data

        Returns:
            ExecutionTimes: New instance with the deserialized data
        """
        ret = ExecutionTimes()
        ret.__dict__.update(cached_obj)
        return ret


class ProviderTimes:
    """
    Provider-reported timing measurements for function execution.

    Stores timing measurements reported by the cloud provider,
    including initialization time and execution time.

    Attributes:
        initialization: Function initialization time in microseconds
        execution: Function execution time in microseconds
    """

    initialization: int
    execution: int

    def __init__(self):
        """Initialize with default values."""
        self.execution = 0
        self.initialization = 0

    @staticmethod
    def deserialize(cached_obj: dict) -> "ProviderTimes":
        """
        Create a ProviderTimes instance from a dictionary.

        Args:
            cached_obj: Dictionary containing serialized timing data

        Returns:
            ProviderTimes: New instance with the deserialized data
        """
        ret = ProviderTimes()
        ret.__dict__.update(cached_obj)
        return ret


class ExecutionStats:
    """
    Statistics for function execution.

    Tracks execution statistics such as memory usage, cold start status,
    and execution failure.

    Attributes:
        memory_used: Amount of memory used in MB (if available)
        cold_start: Whether this was a cold start execution
        failure: Whether the execution failed
    """

    memory_used: Optional[float]
    cold_start: bool
    failure: bool

    def __init__(self):
        """Initialize with default values."""
        self.memory_used = None
        self.cold_start = False
        self.failure = False

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionStats":
        """
        Create an ExecutionStats instance from a dictionary.

        Args:
            cached_obj: Dictionary containing serialized statistics

        Returns:
            ExecutionStats: New instance with the deserialized data
        """
        ret = ExecutionStats()
        ret.__dict__.update(cached_obj)
        return ret


class ExecutionBilling:
    """
    Billing information for function execution.

    Tracks billing-related metrics such as allocated memory,
    billed execution time, and GB-seconds consumed.

    Attributes:
        memory: Allocated memory in MB
        billed_time: Billed execution time in milliseconds
        gb_seconds: GB-seconds consumed (memory/1024 * billed_time/1000)
    """

    _memory: Optional[int]
    _billed_time: Optional[int]
    _gb_seconds: int

    def __init__(self):
        """Initialize with default values."""
        self.memory = None
        self.billed_time = None
        self.gb_seconds = 0

    @property
    def memory(self) -> Optional[int]:
        """
        Get the allocated memory in MB.

        Returns:
            int: Memory allocation in MB, or None if not available
        """
        return self._memory

    @memory.setter
    def memory(self, val: int):
        """
        Set the allocated memory in MB.

        Args:
            val: Memory allocation in MB
        """
        self._memory = val

    @property
    def billed_time(self) -> Optional[int]:
        """
        Get the billed execution time in milliseconds.

        Returns:
            int: Billed time in milliseconds, or None if not available
        """
        return self._billed_time

    @billed_time.setter
    def billed_time(self, val: int):
        """
        Set the billed execution time in milliseconds.

        Args:
            val: Billed time in milliseconds
        """
        self._billed_time = val

    @property
    def gb_seconds(self) -> int:
        """
        Get the GB-seconds consumed.

        Returns:
            int: GB-seconds consumed
        """
        return self._gb_seconds

    @gb_seconds.setter
    def gb_seconds(self, val: int):
        """
        Set the GB-seconds consumed.

        Args:
            val: GB-seconds consumed
        """
        self._gb_seconds = val

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionBilling":
        """
        Create an ExecutionBilling instance from a dictionary.

        Args:
            cached_obj: Dictionary containing serialized billing data

        Returns:
            ExecutionBilling: New instance with the deserialized data
        """
        ret = ExecutionBilling()
        ret.__dict__.update(cached_obj)
        return ret


class ExecutionResult:
    """
    Comprehensive result of a function execution.

    This class captures all timing information, provider metrics, and function
    output from a single function invocation. It provides methods for parsing
    benchmark output and calculating metrics.

    Attributes:
        output: Dictionary containing function output
        request_id: Unique identifier for the request
        times: ExecutionTimes containing client-side timing measurements
        provider_times: ProviderTimes containing platform-reported timings
        stats: ExecutionStats containing resource usage statistics
        billing: ExecutionBilling containing cost-related information
    """

    output: dict
    request_id: str
    times: ExecutionTimes
    provider_times: ProviderTimes
    stats: ExecutionStats
    billing: ExecutionBilling

    def __init__(self):
        """Initialize with default values for all components."""
        self.output = {}
        self.request_id = ""
        self.times = ExecutionTimes()
        self.provider_times = ProviderTimes()
        self.stats = ExecutionStats()
        self.billing = ExecutionBilling()

    @staticmethod
    def from_times(client_time_begin: datetime, client_time_end: datetime) -> "ExecutionResult":
        """
        Create an ExecutionResult with client-side timing information.

        Args:
            client_time_begin: Timestamp when the request was initiated
            client_time_end: Timestamp when the response was received

        Returns:
            ExecutionResult: New instance with calculated client-side timing
        """
        ret = ExecutionResult()
        ret.times.client_begin = client_time_begin
        ret.times.client_end = client_time_end
        ret.times.client = int((client_time_end - client_time_begin) / timedelta(microseconds=1))
        return ret

    def parse_benchmark_output(self, output: dict):
        """
        Parse the output from a benchmark execution.

        Extracts timing information and cold start status from the benchmark output.

        Args:
            output: Dictionary containing benchmark output

        Raises:
            RuntimeError: If the invocation failed (missing required fields)
        """
        self.output = output
        # FIXME: temporary handling of errorenous invocation
        if "is_cold" not in self.output:
            raise RuntimeError(f"Invocation failed! Reason: {output['result']}")
        self.stats.cold_start = self.output["is_cold"]
        self.times.benchmark = int(
            (
                datetime.fromtimestamp(float(self.output["end"]))
                - datetime.fromtimestamp(float(self.output["begin"]))
            )
            / timedelta(microseconds=1)
        )

    @staticmethod
    def deserialize(cached_config: dict) -> "ExecutionResult":
        """
        Create an ExecutionResult instance from a cached configuration.

        Args:
            cached_config: Dictionary containing serialized execution result

        Returns:
            ExecutionResult: New instance with the deserialized data
        """
        ret = ExecutionResult()
        ret.times = ExecutionTimes.deserialize(cached_config["times"])
        ret.billing = ExecutionBilling.deserialize(cached_config["billing"])
        ret.provider_times = ProviderTimes.deserialize(cached_config["provider_times"])
        ret.stats = ExecutionStats.deserialize(cached_config["stats"])
        ret.request_id = cached_config["request_id"]
        ret.output = cached_config["output"]
        return ret


class Trigger(ABC, LoggingBase):
    """
    Abstract base class for function triggers.

    A trigger represents a mechanism for invoking a serverless function,
    such as HTTP requests, direct SDK invocations, or event-based triggers.
    Each trigger type implements synchronous and asynchronous invocation methods.

    Includes a helper method for HTTP invocations using pycurl.
    """

    class TriggerType(Enum):
        """
        Enumeration of supported trigger types.

        Defines the different mechanisms for invoking serverless functions:
        - HTTP: Invocation via HTTP requests
        - LIBRARY: Invocation via cloud provider SDK
        - STORAGE: Invocation via storage events
        """

        HTTP = "http"
        LIBRARY = "library"
        STORAGE = "storage"

        @staticmethod
        def get(name: str) -> "Trigger.TriggerType":
            """
            Get a TriggerType by name (case-insensitive).

            Args:
                name: Name of the trigger type

            Returns:
                TriggerType: The matching trigger type

            Raises:
                Exception: If no matching trigger type is found
            """
            for member in Trigger.TriggerType:
                if member.value.lower() == name.lower():
                    return member
            raise Exception("Unknown trigger type {}".format(name))

    def _http_invoke(self, payload: dict, url: str, verify_ssl: bool = True) -> ExecutionResult:
        """
        Invoke a function via HTTP request.

        Makes a HTTP POST request using pycurl to the given URL, with the provided payload,
        and processes the response into an ExecutionResult.

        Args:
            payload: Dictionary containing the function input
            url: URL to invoke the function
            verify_ssl: Whether to verify SSL certificates

        Returns:
            ExecutionResult: Result of the function execution

        Raises:
            RuntimeError: If the invocation fails or produces invalid output
        """
        import pycurl
        from io import BytesIO

        c = pycurl.Curl()
        c.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, url)
        if not verify_ssl:
            c.setopt(pycurl.SSL_VERIFYHOST, 0)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)

        c.setopt(pycurl.POSTFIELDS, json.dumps(payload))
        begin = datetime.now()
        c.perform()
        end = datetime.now()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        conn_time = c.getinfo(pycurl.PRETRANSFER_TIME)
        receive_time = c.getinfo(pycurl.STARTTRANSFER_TIME)

        try:
            output = json.loads(data.getvalue())

            if status_code != 200:
                self.logging.error("Invocation on URL {} failed!".format(url))
                self.logging.error("Output: {}".format(output))
                raise RuntimeError(f"Failed invocation of function! Output: {output}")

            self.logging.debug("Invoke of function was successful")
            result = ExecutionResult.from_times(begin, end)
            result.times.http_startup = conn_time
            result.times.http_first_byte_return = receive_time
            # OpenWhisk will not return id on a failure
            if "request_id" not in output:
                raise RuntimeError(f"Cannot process allocation with output: {output}")
            result.request_id = output["request_id"]
            # General benchmark output parsing
            result.parse_benchmark_output(output)
            return result
        except json.decoder.JSONDecodeError:
            self.logging.error("Invocation on URL {} failed!".format(url))
            if len(data.getvalue()) > 0:
                self.logging.error("Output: {}".format(data.getvalue().decode()))
            else:
                self.logging.error("No output provided!")
            raise RuntimeError(f"Failed invocation of function! Output: {data.getvalue().decode()}")

    @staticmethod
    @abstractmethod
    def trigger_type() -> "Trigger.TriggerType":
        """
        Get the type of this trigger.

        Returns:
            TriggerType: The type of this trigger
        """
        pass

    @abstractmethod
    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke a function with the given payload.

        Args:
            payload: Dictionary containing the function input

        Returns:
            ExecutionResult: Result of the function execution
        """
        pass

    @abstractmethod
    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke a function with the given payload.

        Args:
            payload: Dictionary containing the function input

        Returns:
            Future: Future object representing the pending execution
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize the trigger to a dictionary.

        Returns:
            dict: Dictionary representation of the trigger
        """
        pass

    @staticmethod
    @abstractmethod
    def deserialize(cached_config: dict) -> "Trigger":
        """
        Create a Trigger instance from a cached configuration.

        Args:
            cached_config: Dictionary containing serialized trigger

        Returns:
            Trigger: New instance with the deserialized data
        """
        pass


class Language(Enum):
    """
    Enumeration of supported programming languages.

    Currently supports Python and Node.js for serverless functions.
    """

    PYTHON = "python"
    NODEJS = "nodejs"

    @staticmethod
    def deserialize(val: str) -> Language:
        """
        Get a Language by string value.

        Args:
            val: String representation of the language

        Returns:
            Language: The matching language enum

        Raises:
            Exception: If no matching language is found
        """
        for member in Language:
            if member.value == val:
                return member
        raise Exception(f"Unknown language type {val}")


class Architecture(Enum):
    """
    Enumeration of supported CPU architectures.

    Defines the CPU architectures that can be targeted for function deployment.
    """

    X86 = "x64"
    ARM = "arm64"

    def serialize(self) -> str:
        """
        Serialize the architecture to a string.

        Returns:
            str: String representation of the architecture
        """
        return self.value

    @staticmethod
    def deserialize(val: str) -> Architecture:
        """
        Get an Architecture by string value.

        Args:
            val: String representation of the architecture

        Returns:
            Architecture: The matching architecture enum

        Raises:
            Exception: If no matching architecture is found
        """
        for member in Architecture:
            if member.value == val:
                return member
        raise Exception(f"Unknown architecture type {val}")


@dataclass
class Runtime:
    """
    Runtime configuration for a serverless function.

    Defines the language and version for a function's runtime environment.

    Attributes:
        language: Programming language (Python, Node.js)
        version: Version string of the language runtime
    """

    language: Language
    version: str

    def serialize(self) -> dict:
        """
        Serialize the runtime to a dictionary.

        Returns:
            dict: Dictionary representation of the runtime
        """
        return {"language": self.language.value, "version": self.version}

    @staticmethod
    def deserialize(config: dict) -> Runtime:
        """
        Create a Runtime instance from a dictionary.

        Args:
            config: Dictionary containing serialized runtime

        Returns:
            Runtime: New instance with the deserialized data
        """
        languages = {"python": Language.PYTHON, "nodejs": Language.NODEJS}
        return Runtime(language=languages[config["language"]], version=config["version"])


T = TypeVar("T", bound="FunctionConfig")


@dataclass
class FunctionConfig:
    """
    Configuration for a serverless function.

    Defines the resources, runtime, and architecture for a function deployment.

    Attributes:
        timeout: Maximum execution time in seconds
        memory: Memory allocation in MB
        runtime: Runtime environment configuration
        architecture: CPU architecture for deployment
    """

    timeout: int
    memory: int
    runtime: Runtime
    architecture: Architecture = Architecture.X86

    @staticmethod
    def _from_benchmark(benchmark: Benchmark, obj_type: Type[T]) -> T:
        """
        Create a FunctionConfig subclass instance from a benchmark.

        Args:
            benchmark: Benchmark to extract configuration from
            obj_type: Type of FunctionConfig to create

        Returns:
            T: New instance of the specified FunctionConfig subclass
        """
        runtime = Runtime(language=benchmark.language, version=benchmark.language_version)
        architecture = Architecture.deserialize(benchmark._experiment_config._architecture)
        cfg = obj_type(
            timeout=benchmark.benchmark_config.timeout,
            memory=benchmark.benchmark_config.memory,
            runtime=runtime,
            architecture=architecture,
        )
        return cfg

    @staticmethod
    def from_benchmark(benchmark: Benchmark) -> FunctionConfig:
        """
        Create a FunctionConfig instance from a benchmark.

        Args:
            benchmark: Benchmark to extract configuration from

        Returns:
            FunctionConfig: New instance with the benchmark's configuration
        """
        return FunctionConfig._from_benchmark(benchmark, FunctionConfig)

    @staticmethod
    def deserialize(data: dict) -> FunctionConfig:
        """
        Create a FunctionConfig instance from a dictionary.

        Args:
            data: Dictionary containing serialized function configuration

        Returns:
            FunctionConfig: New instance with the deserialized data
        """
        keys = list(FunctionConfig.__dataclass_fields__.keys())
        data = {k: v for k, v in data.items() if k in keys}
        data["runtime"] = Runtime.deserialize(data["runtime"])
        return FunctionConfig(**data)

    def serialize(self) -> dict:
        """
        Serialize the function configuration to a dictionary.

        Returns:
            dict: Dictionary representation of the function configuration
        """
        return self.__dict__


class Function(LoggingBase):
    """
    Abstract base class for serverless functions.

    This class represents a deployed serverless function with its configuration
    and contains a list of associated triggers.
    Each cloud provider (AWS, Azure, GCP, etc.) implements a subclass with
    platform-specific functionality.

    Represents a deployable unit of code on a FaaS platform. Contains details
    about the benchmark it belongs to, its name, code hash, configuration,
    and associated triggers. Subclasses implement provider-specific details.

    Attributes:
        config: Function configuration
        name: Name of the deployed function
        benchmark: Name of the benchmark implemented by this function
        code_package_hash: Hash of the deployed code package
        updated_code: Whether the code has been updated since deployment
    """

    def __init__(self, benchmark: str, name: str, code_hash: str, cfg: FunctionConfig):
        """
        Initialize a Function instance.

        Args:
            benchmark: Name of the benchmark
            name: Name of the function
            code_hash: Hash of the code package
            cfg: Function configuration
        """
        super().__init__()
        self._benchmark = benchmark
        self._name = name
        self._code_package_hash = code_hash
        self._updated_code = False
        self._triggers: Dict[Trigger.TriggerType, List[Trigger]] = {}
        self._cfg = cfg

    @property
    def config(self) -> FunctionConfig:
        """
        Get the function configuration.

        Returns:
            FunctionConfig: Configuration of the function
        """
        return self._cfg

    @property
    def name(self) -> str:
        """
        Get the name of the function.

        Returns:
            str: Name of the function
        """
        return self._name

    @property
    def benchmark(self) -> str:
        """
        Get the name of the benchmark.

        Returns:
            str: Name of the benchmark
        """
        return self._benchmark

    @property
    def code_package_hash(self) -> str:
        """
        Get the hash of the code package.

        Returns:
            str: Hash of the code package
        """
        return self._code_package_hash

    @code_package_hash.setter
    def code_package_hash(self, new_hash: str):
        """
        Set the hash of the code package.

        Args:
            new_hash: New hash of the code package
        """
        self._code_package_hash = new_hash

    @property
    def updated_code(self) -> bool:
        """
        Check if the code has been updated since deployment.

        Returns:
            bool: True if the code has been updated, False otherwise
        """
        return self._updated_code

    @updated_code.setter
    def updated_code(self, val: bool):
        """
        Set whether the code has been updated since deployment.

        Args:
            val: True if the code has been updated, False otherwise
        """
        self._updated_code = val

    def triggers_all(self) -> List[Trigger]:
        """
        Get all triggers associated with this function.

        Returns:
            List[Trigger]: List of all triggers
        """
        return [trig for trigger_type, triggers in self._triggers.items() for trig in triggers]

    def triggers(self, trigger_type: Trigger.TriggerType) -> List[Trigger]:
        """
        Get triggers of a specific type associated with this function.

        Args:
            trigger_type: Type of triggers to get

        Returns:
            List[Trigger]: List of triggers of the specified type
        """
        try:
            return self._triggers[trigger_type]
        except KeyError:
            return []

    def add_trigger(self, trigger: Trigger):
        """
        Add a trigger to this function.

        Args:
            trigger: Trigger to add
        """
        if trigger.trigger_type() not in self._triggers:
            self._triggers[trigger.trigger_type()] = [trigger]
        else:
            self._triggers[trigger.trigger_type()].append(trigger)

    def serialize(self) -> dict:
        """
        Serialize the function to a dictionary.

        Returns:
            dict: Dictionary representation of the function
        """
        return {
            "name": self._name,
            "hash": self._code_package_hash,
            "benchmark": self._benchmark,
            "config": self.config.serialize(),
            "triggers": [
                obj.serialize() for t_type, triggers in self._triggers.items() for obj in triggers
            ],
        }

    @staticmethod
    @abstractmethod
    def deserialize(cached_config: dict) -> "Function":
        """
        Create a Function instance from a cached configuration.

        Args:
            cached_config: Dictionary containing serialized function

        Returns:
            Function: New instance with the deserialized data
        """
        pass

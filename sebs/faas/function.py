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

"""
Defines core classes for representing FaaS functions, their configurations,
triggers, and execution results within the SeBS framework.

All times are reported in microseconds unless otherwise specified.
"""


class ExecutionTimes:
    """
    Stores various client-side and benchmark-internal execution timings.
    All times are in microseconds.

    Attributes:
        client: Total client-perceived execution time.
        client_begin: Timestamp when the client initiated the request.
        client_end: Timestamp when the client received the full response.
        benchmark: Execution time measured within the benchmark code itself.
        initialization: Initialization time, often part of cold start (provider-reported or inferred).
        http_startup: Time until TCP connection is established for HTTP triggers.
        http_first_byte_return: Time until the first byte of the HTTP response is received.
    """
    client: int
    client_begin: datetime
    client_end: datetime
    benchmark: int
    initialization: int
    http_startup: int
    http_first_byte_return: int

    def __init__(self):
        """Initialize ExecutionTimes with default zero values."""
        self.client = 0
        self.initialization = 0
        self.benchmark = 0
        # Ensure all attributes are initialized, even if not set to 0 by default.
        # For datetime objects, None might be more appropriate if not immediately known.
        # However, the current deserialize method assumes they exist.
        # For now, we'll leave them uninitialized here if not explicitly set to 0.
        # Consider adding default None or now() for datetime if appropriate.

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionTimes":
        """
        Deserialize an ExecutionTimes object from a dictionary.

        :param cached_obj: Dictionary containing ExecutionTimes data.
        :return: An ExecutionTimes instance.
        """
        ret = ExecutionTimes()
        ret.__dict__.update(cached_obj)
        return ret


class ProviderTimes:
    """
    Stores execution and initialization times as reported by the FaaS provider.
    All times are in microseconds.

    Attributes:
        initialization: Initialization duration (e.g., cold start init phase).
        execution: Execution duration of the function code.
    """
    initialization: int
    execution: int

    def __init__(self):
        """Initialize ProviderTimes with default zero values."""
        self.execution = 0
        self.initialization = 0

    @staticmethod
    def deserialize(cached_obj: dict) -> "ProviderTimes":
        """
        Deserialize a ProviderTimes object from a dictionary.

        :param cached_obj: Dictionary containing ProviderTimes data.
        :return: A ProviderTimes instance.
        """
        ret = ProviderTimes()
        ret.__dict__.update(cached_obj)
        return ret


class ExecutionStats:
    """
    Stores statistical information about a function execution.

    Attributes:
        memory_used: Memory used by the function execution (in MB or other provider unit).
        cold_start: Boolean indicating if this was a cold start.
        failure: Boolean indicating if the invocation failed.
    """
    memory_used: Optional[float]
    cold_start: bool
    failure: bool

    def __init__(self):
        """Initialize ExecutionStats with default values."""
        self.memory_used = None
        self.cold_start = False
        self.failure = False

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionStats":
        """
        Deserialize an ExecutionStats object from a dictionary.

        :param cached_obj: Dictionary containing ExecutionStats data.
        :return: An ExecutionStats instance.
        """
        ret = ExecutionStats()
        ret.__dict__.update(cached_obj)
        return ret


class ExecutionBilling:
    """
    Stores billing-related information for a function execution.

    Attributes:
        memory: Configured memory for the function (in MB or provider unit).
        billed_time: Duration for which the execution was billed (in provider-specific units, often ms).
        gb_seconds: A common billing unit, calculated as (memory_GB * billed_duration_seconds).
    """
    _memory: Optional[int]
    _billed_time: Optional[int]
    _gb_seconds: int # Should this also be optional or default to 0?

    def __init__(self):
        """Initialize ExecutionBilling with default values."""
        self._memory = None # Use underscore to indicate it's managed by property
        self._billed_time = None
        self._gb_seconds = 0

    @property
    def memory(self) -> Optional[int]:
        """Configured memory for the function (e.g., in MB)."""
        return self._memory

    @memory.setter
    def memory(self, val: int):
        """Set the configured memory."""
        self._memory = val

    @property
    def billed_time(self) -> Optional[int]:
        """Billed duration for the execution (e.g., in milliseconds)."""
        return self._billed_time

    @billed_time.setter
    def billed_time(self, val: int):
        """Set the billed duration."""
        self._billed_time = val

    @property
    def gb_seconds(self) -> int:
        """Computed GB-seconds for the execution."""
        return self._gb_seconds

    @gb_seconds.setter
    def gb_seconds(self, val: int):
        """Set the computed GB-seconds."""
        self._gb_seconds = val

    @staticmethod
    def deserialize(cached_obj: dict) -> "ExecutionBilling":
        """
        Deserialize an ExecutionBilling object from a dictionary.

        :param cached_obj: Dictionary containing ExecutionBilling data.
        :return: An ExecutionBilling instance.
        """
        ret = ExecutionBilling()
        # Handle cases where keys might be missing in older cached_obj
        ret._memory = cached_obj.get("_memory")
        ret._billed_time = cached_obj.get("_billed_time")
        ret._gb_seconds = cached_obj.get("_gb_seconds", 0) # Default to 0 if missing
        return ret


class ExecutionResult:
    """
    Encapsulates all results from a single function invocation.

    Includes benchmark output, request ID, various timings, provider-specific times,
    execution statistics, and billing information.
    """
    output: dict
    request_id: str
    times: ExecutionTimes
    provider_times: ProviderTimes
    stats: ExecutionStats
    billing: ExecutionBilling

    def __init__(self):
        """Initialize an empty ExecutionResult."""
        self.output = {}
        self.request_id = ""
        self.times = ExecutionTimes()
        self.provider_times = ProviderTimes()
        self.stats = ExecutionStats()
        self.billing = ExecutionBilling()

    @staticmethod
    def from_times(client_time_begin: datetime, client_time_end: datetime) -> "ExecutionResult":
        """
        Create an ExecutionResult instance initialized with client begin and end times.

        Calculates the total client-perceived duration.

        :param client_time_begin: Timestamp when the client initiated the request.
        :param client_time_end: Timestamp when the client received the full response.
        :return: An ExecutionResult instance.
        """
        ret = ExecutionResult()
        ret.times.client_begin = client_time_begin
        ret.times.client_end = client_time_end
        ret.times.client = int((client_time_end - client_time_begin) / timedelta(microseconds=1))
        return ret

    def parse_benchmark_output(self, output: dict):
        """
        Parse the output from the benchmark function.

        Extracts standard fields like 'is_cold', 'begin', and 'end' timestamps
        to populate `stats.cold_start` and `times.benchmark`.

        :param output: The dictionary returned by the benchmark function.
        :raises RuntimeError: If 'is_cold' is not in the output, indicating a potential failure.
        """
        self.output = output
        # FIXME: temporary handling of errorenous invocation
        if "is_cold" not in self.output:
            # More informative error message
            error_reason = output.get('result', output.get('body', str(output)))
            raise RuntimeError(f"Invocation failed! Output: {error_reason}")
        self.stats.cold_start = self.output["is_cold"]
        # Ensure 'begin' and 'end' are present and are valid numbers before conversion
        if "begin" in self.output and "end" in self.output:
            try:
                begin_ts = float(self.output["begin"])
                end_ts = float(self.output["end"])
                self.times.benchmark = int(
                    (datetime.fromtimestamp(end_ts) - datetime.fromtimestamp(begin_ts))
                    / timedelta(microseconds=1)
                )
            except (ValueError, TypeError) as e:
                self.logging.error(f"Could not parse benchmark begin/end times from output: {e}")
                self.times.benchmark = 0 # Or some other indicator of parsing failure
        else:
            self.logging.warning("Benchmark begin/end times not found in output.")
            self.times.benchmark = 0


    @staticmethod
    def deserialize(cached_config: dict) -> "ExecutionResult":
        """
        Deserialize an ExecutionResult object from a dictionary.

        :param cached_config: Dictionary containing ExecutionResult data.
        :return: An ExecutionResult instance.
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

    Defines the interface for different trigger types (e.g., HTTP, Library, Storage).
    Includes a helper method for HTTP invocations using pycurl.

    FIXME: implement a generic HTTP invocation and specialize input and output
    processing in classes. (This comment is from the original code)
    """
    class TriggerType(Enum):
        """Enumeration of supported trigger types."""
        HTTP = "http"
        LIBRARY = "library"
        STORAGE = "storage"

        @staticmethod
        def get(name: str) -> "Trigger.TriggerType":
            """
            Get a TriggerType enum member by its string name. Case-insensitive.

            :param name: The string name of the trigger type (e.g., "http").
            :return: The corresponding TriggerType enum member.
            :raises Exception: If the name does not match any known trigger type.
            """
            for member in Trigger.TriggerType:
                if member.value.lower() == name.lower():
                    return member
            raise Exception("Unknown trigger type {}".format(member)) # Original used member, should be name

    def _http_invoke(self, payload: dict, url: str, verify_ssl: bool = True) -> ExecutionResult:
        """
        Perform an HTTP POST request to the given URL with the provided payload.

        Uses pycurl for the HTTP request. Parses the JSON response and populates
        an ExecutionResult object.

        :param payload: Dictionary to be sent as JSON in the request body.
        :param url: The URL to invoke.
        :param verify_ssl: Whether to verify SSL certificates (default: True).
        :return: An ExecutionResult object.
        :raises RuntimeError: If the invocation fails (e.g., non-200 status, JSON decode error).
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

    # FIXME: 3.7+, future annotations
    # FIXME: 3.7+, future annotations
    @staticmethod
    @abstractmethod
    def trigger_type() -> "Trigger.TriggerType":
        """Return the type of this trigger (e.g., HTTP, LIBRARY)."""
        pass

    @abstractmethod
    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke the function with the given payload.

        :param payload: The payload to send to the function.
        :return: An ExecutionResult object.
        """
        pass

    @abstractmethod
    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke the function with the given payload.

        :param payload: The payload to send to the function.
        :return: A Future object representing the asynchronous invocation.
        """
        pass

    @abstractmethod
    def serialize(self) -> dict:
        """
        Serialize the trigger's state to a dictionary.

        :return: A dictionary representation of the trigger.
        """
        pass

    @staticmethod
    @abstractmethod
    def deserialize(cached_config: dict) -> "Trigger":
        """
        Deserialize a Trigger object from a dictionary.

        :param cached_config: Dictionary containing Trigger data.
        :return: A Trigger instance.
        """
        pass


class Language(Enum):
    """Enumeration of supported programming languages for FaaS functions."""
    PYTHON = "python"
    NODEJS = "nodejs"

    # FIXME: 3.7+ python with future annotations
    @staticmethod
    def deserialize(val: str) -> Language:
        """
        Deserialize a string value to a Language enum member. Case-insensitive.

        :param val: The string name of the language (e.g., "python").
        :return: The corresponding Language enum member.
        :raises Exception: If the value does not match any known language.
        """
        for member in Language:
            if member.value.lower() == val.lower(): # Make comparison case-insensitive
                return member
        raise Exception(f"Unknown language type {val}")


class Architecture(Enum):
    """Enumeration of supported CPU architectures for FaaS functions."""
    X86 = "x64"
    ARM = "arm64"

    def serialize(self) -> str:
        """Serialize the Architecture enum member to its string value."""
        return self.value

    @staticmethod
    def deserialize(val: str) -> Architecture:
        """
        Deserialize a string value to an Architecture enum member. Case-insensitive.

        :param val: The string name of the architecture (e.g., "x64").
        :return: The corresponding Architecture enum member.
        :raises Exception: If the value does not match any known architecture.
        """
        for member in Architecture:
            if member.value.lower() == val.lower(): # Make comparison case-insensitive
                return member
        raise Exception(f"Unknown architecture type {val}")


@dataclass
class Runtime:
    """
    Represents the runtime environment of a FaaS function.

    Attributes:
        language: The programming language (Language enum).
        version: The specific version string of the language runtime (e.g., "3.8", "12").
    """
    language: Language
    version: str

    def serialize(self) -> dict:
        """
        Serialize the Runtime to a dictionary.

        :return: Dictionary with "language" and "version".
        """
        return {"language": self.language.value, "version": self.version}

    @staticmethod
    def deserialize(config: dict) -> Runtime:
        """
        Deserialize a Runtime object from a dictionary.

        :param config: Dictionary with "language" and "version".
        :return: A Runtime instance.
        """
        return Runtime(language=Language.deserialize(config["language"]), version=config["version"])


T = TypeVar("T", bound="FunctionConfig")


@dataclass
class FunctionConfig:
    """
    Dataclass for storing the configuration of a FaaS function.

    Attributes:
        timeout: Function execution timeout in seconds.
        memory: Memory allocated to the function (in MB or provider-specific units).
        runtime: The Runtime environment for the function.
        architecture: The CPU architecture for the function (default: X86).
    """
    timeout: int
    memory: int
    runtime: Runtime
    architecture: Architecture = Architecture.X86 # Default to X86

    @staticmethod
    def _from_benchmark(benchmark: Benchmark, obj_type: Type[T]) -> T:
        """
        Internal helper to create a FunctionConfig (or subclass) from a Benchmark object.

        :param benchmark: The Benchmark instance.
        :param obj_type: The specific FunctionConfig class type to instantiate.
        :return: An instance of obj_type.
        """
        runtime = Runtime(language=benchmark.language, version=benchmark.language_version)
        # Ensure benchmark._experiment_config._architecture is available and valid
        architecture_str = getattr(getattr(benchmark, '_experiment_config', object()), '_architecture', 'x64')
        architecture = Architecture.deserialize(architecture_str)
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
        Create a FunctionConfig instance from a Benchmark object.

        :param benchmark: The Benchmark instance.
        :return: A FunctionConfig instance.
        """
        return FunctionConfig._from_benchmark(benchmark, FunctionConfig)

    @staticmethod
    def deserialize(data: dict) -> FunctionConfig:
        """
        Deserialize a FunctionConfig object from a dictionary.

        :param data: Dictionary containing FunctionConfig data.
        :return: A FunctionConfig instance.
        """
        # Filter for known fields to avoid errors with extra keys in data
        known_keys = {field.name for field in FunctionConfig.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_keys}

        filtered_data["runtime"] = Runtime.deserialize(filtered_data["runtime"])
        if "architecture" in filtered_data: # Handle optional architecture
            filtered_data["architecture"] = Architecture.deserialize(filtered_data["architecture"])
        else: # Default if not present
            filtered_data["architecture"] = Architecture.X86
        return FunctionConfig(**filtered_data)

    def serialize(self) -> dict:
        """
        Serialize the FunctionConfig to a dictionary.

        Converts Runtime and Architecture to their serializable forms.

        :return: A dictionary representation of the FunctionConfig.
        """
        # Manually construct dict to ensure enums are serialized correctly
        return {
            "timeout": self.timeout,
            "memory": self.memory,
            "runtime": self.runtime.serialize(),
            "architecture": self.architecture.serialize()
        }


class Function(LoggingBase, ABC): # Added ABC
    """
    Abstract base class for a FaaS function.

    Represents a deployable unit of code on a FaaS platform. Contains details
    about the benchmark it belongs to, its name, code hash, configuration,
    and associated triggers. Subclasses implement provider-specific details.
    """
    def __init__(self, benchmark: str, name: str, code_hash: str, cfg: FunctionConfig):
        """
        Initialize a new Function.

        :param benchmark: The name of the benchmark this function implements.
        :param name: The name of the function on the FaaS platform.
        :param code_hash: A hash of the function's code package, for change detection.
        :param cfg: The FunctionConfig object for this function.
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
        """The configuration of this function (timeout, memory, runtime, etc.)."""
        return self._cfg

    @property
    def name(self) -> str: # Added return type hint
        """The name of the function on the FaaS platform."""
        return self._name

    @property
    def benchmark(self) -> str: # Added return type hint
        """The name of the benchmark this function belongs to."""
        return self._benchmark

    @property
    def code_package_hash(self) -> str: # Added return type hint
        """A hash of the function's code package."""
        return self._code_package_hash

    @code_package_hash.setter
    def code_package_hash(self, new_hash: str):
        """Set a new code package hash (e.g., after an update)."""
        self._code_package_hash = new_hash

    @property
    def updated_code(self) -> bool:
        """Flag indicating if the function's code has been updated since last deployment."""
        return self._updated_code

    @updated_code.setter
    def updated_code(self, val: bool):
        """Set the updated_code flag."""
        self._updated_code = val

    def triggers_all(self) -> List[Trigger]:
        """Return a list of all triggers associated with this function."""
        return [trig for trigger_type, triggers in self._triggers.items() for trig in triggers]

    def triggers(self, trigger_type: Trigger.TriggerType) -> List[Trigger]:
        """
        Return a list of triggers of a specific type associated with this function.

        :param trigger_type: The type of triggers to retrieve.
        :return: A list of Trigger objects, or an empty list if none of that type exist.
        """
        try:
            return self._triggers[trigger_type]
        except KeyError:
            return []

    def add_trigger(self, trigger: Trigger):
        """
        Add a trigger to this function.

        :param trigger: The Trigger object to add.
        """
        if trigger.trigger_type() not in self._triggers:
            self._triggers[trigger.trigger_type()] = [trigger]
        else:
            self._triggers[trigger.trigger_type()].append(trigger)

    def serialize(self) -> dict:
        """
        Serialize the Function's state to a dictionary.

        Includes name, hash, benchmark, config, and all triggers.

        :return: A dictionary representation of the Function.
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
        Deserialize a Function object from a dictionary.

        This method must be implemented by FaaS provider-specific subclasses.

        :param cached_config: Dictionary containing Function data.
        :return: A Function instance.
        """
        pass

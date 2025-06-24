"""Trigger implementations for OpenWhisk function invocation in SeBS.

This module provides different trigger types for invoking OpenWhisk functions,
including library-based (CLI) triggers and HTTP-based triggers. Each trigger
type handles the specific invocation method and result parsing for OpenWhisk.

Classes:
    LibraryTrigger: CLI-based function invocation using wsk tool
    HTTPTrigger: HTTP-based function invocation using web actions
"""

import concurrent.futures
import datetime
import json
import subprocess
from typing import Dict, List, Optional, Any  # noqa

from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    """
    CLI-based trigger for OpenWhisk function invocation.

    This trigger uses the wsk CLI tool to invoke OpenWhisk actions directly,
    providing synchronous and asynchronous invocation capabilities. It handles
    parameter passing and result parsing for CLI-based invocations.

    Attributes:
        fname: Name of the OpenWhisk action to invoke
        _wsk_cmd: Complete WSK CLI command for function invocation

    Example:
        >>> trigger = LibraryTrigger("my-function", ["wsk", "-i"])
        >>> result = trigger.sync_invoke({"key": "value"})
    """

    def __init__(self, fname: str, wsk_cmd: Optional[List[str]] = None) -> None:
        """
        Initialize library trigger for OpenWhisk function.

        Args:
            fname: Name of the OpenWhisk action to invoke
            wsk_cmd: Optional WSK CLI command prefix (including flags)
        """
        super().__init__()
        self.fname = fname
        if wsk_cmd:
            self._wsk_cmd = [*wsk_cmd, "action", "invoke", "--result", self.fname]

    @staticmethod
    def trigger_type() -> "Trigger.TriggerType":
        """
        Get the trigger type identifier.

        Returns:
            TriggerType.LIBRARY for CLI-based invocation
        """
        return Trigger.TriggerType.LIBRARY

    @property
    def wsk_cmd(self) -> List[str]:
        """
        Get the complete WSK CLI command for invocation.

        Returns:
            List of command arguments for WSK CLI invocation

        Raises:
            AssertionError: If wsk_cmd has not been set
        """
        assert self._wsk_cmd
        return self._wsk_cmd

    @wsk_cmd.setter
    def wsk_cmd(self, wsk_cmd: List[str]) -> None:
        """
        Set the WSK CLI command prefix.

        Args:
            wsk_cmd: WSK CLI command prefix (including any flags)
        """
        self._wsk_cmd = [*wsk_cmd, "action", "invoke", "--result", self.fname]

    @staticmethod
    def get_command(payload: Dict[str, Any]) -> List[str]:
        """
        Convert payload dictionary to WSK CLI parameter arguments.

        Args:
            payload: Dictionary of parameters to pass to the function

        Returns:
            List of CLI arguments for passing parameters to WSK

        Example:
            >>> get_command({"key1": "value1", "key2": 42})
            ["--param", "key1", '"value1"', "--param", "key2", "42"]
        """
        params = []
        for key, value in payload.items():
            params.append("--param")
            params.append(key)
            params.append(json.dumps(value))
        return params

    def sync_invoke(self, payload: Dict[str, Any]) -> ExecutionResult:
        """
        Synchronously invoke the OpenWhisk function via CLI.

        Args:
            payload: Dictionary of parameters to pass to the function

        Returns:
            ExecutionResult containing timing information and function output
        """
        command = self.wsk_cmd + self.get_command(payload)
        error = None
        try:
            begin = datetime.datetime.now()
            response = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            end = datetime.datetime.now()
            parsed_response = response.stdout.decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            end = datetime.datetime.now()
            error = e

        openwhisk_result = ExecutionResult.from_times(begin, end)
        if error is not None:
            self.logging.error("Invocation of {} failed!".format(self.fname))
            openwhisk_result.stats.failure = True
            return openwhisk_result

        return_content = json.loads(parsed_response)
        openwhisk_result.parse_benchmark_output(return_content)
        return openwhisk_result

    def async_invoke(self, payload: Dict[str, Any]) -> concurrent.futures.Future:
        """
        Asynchronously invoke the OpenWhisk function via CLI.

        Args:
            payload: Dictionary of parameters to pass to the function

        Returns:
            Future object that will contain the ExecutionResult
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> Dict[str, str]:
        """
        Serialize trigger configuration to dictionary.

        Returns:
            Dictionary containing trigger type and function name
        """
        return {"type": "Library", "name": self.fname}

    @staticmethod
    def deserialize(obj: Dict[str, str]) -> Trigger:
        """
        Deserialize trigger from configuration dictionary.

        Args:
            obj: Dictionary containing serialized trigger data

        Returns:
            LibraryTrigger instance
        """
        return LibraryTrigger(obj["name"])

    @staticmethod
    def typename() -> str:
        """
        Get the trigger type name.

        Returns:
            String identifier for this trigger type
        """
        return "OpenWhisk.LibraryTrigger"


class HTTPTrigger(Trigger):
    """
    HTTP-based trigger for OpenWhisk web action invocation.

    This trigger uses HTTP requests to invoke OpenWhisk web actions,
    providing an alternative to CLI-based invocation. It inherits HTTP
    invocation capabilities from the base Trigger class.

    Attributes:
        fname: Name of the OpenWhisk action
        url: HTTP URL for the web action endpoint

    Example:
        >>> trigger = HTTPTrigger(
        ...     "my-function",
        ...     "https://openwhisk.example.com/api/v1/web/guest/default/my-function.json"
        ... )
        >>> result = trigger.sync_invoke({"key": "value"})
    """

    def __init__(self, fname: str, url: str) -> None:
        """
        Initialize HTTP trigger for OpenWhisk web action.

        Args:
            fname: Name of the OpenWhisk action
            url: HTTP URL for the web action endpoint
        """
        super().__init__()
        self.fname = fname
        self.url = url

    @staticmethod
    def typename() -> str:
        """
        Get the trigger type name.

        Returns:
            String identifier for this trigger type
        """
        return "OpenWhisk.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """
        Get the trigger type identifier.

        Returns:
            TriggerType.HTTP for HTTP-based invocation
        """
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: Dict[str, Any]) -> ExecutionResult:
        """
        Synchronously invoke the OpenWhisk function via HTTP.

        Args:
            payload: Dictionary of parameters to pass to the function

        Returns:
            ExecutionResult containing timing information and function output
        """
        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url, False)

    def async_invoke(self, payload: Dict[str, Any]) -> concurrent.futures.Future:
        """
        Asynchronously invoke the OpenWhisk function via HTTP.

        Args:
            payload: Dictionary of parameters to pass to the function

        Returns:
            Future object that will contain the ExecutionResult
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> Dict[str, str]:
        """
        Serialize trigger configuration to dictionary.

        Returns:
            Dictionary containing trigger type, function name, and URL
        """
        return {"type": "HTTP", "fname": self.fname, "url": self.url}

    @staticmethod
    def deserialize(obj: Dict[str, str]) -> Trigger:
        """
        Deserialize trigger from configuration dictionary.

        Args:
            obj: Dictionary containing serialized trigger data

        Returns:
            HTTPTrigger instance
        """
        return HTTPTrigger(obj["fname"], obj["url"])

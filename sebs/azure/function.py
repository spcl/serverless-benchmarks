"""Azure Function implementation for SeBS benchmarking.

This module provides the Azure-specific implementation of serverless functions
for the SeBS benchmarking suite. It handles Azure Function representation,
serialization, and deserialization with Azure-specific storage configuration.

The AzureFunction class extends the base Function class to include Azure-specific
attributes like function storage accounts and Azure trigger configurations.

Example:
    Basic usage for creating an Azure Function:

    ```python
    from sebs.azure.function import AzureFunction
    from sebs.azure.config import AzureResources
    from sebs.faas.function import FunctionConfig

    # Create function with Azure-specific storage
    function = AzureFunction(
        name="my-function",
        benchmark="test-benchmark",
        code_hash="abc123",
        function_storage=storage_account,
        cfg=function_config
    )
    ```
"""

from sebs.azure.config import AzureResources
from sebs.faas.function import Function, FunctionConfig


class AzureFunction(Function):
    """Azure Function implementation for SeBS benchmarking.

    This class represents an Azure Function with Azure-specific attributes
    and configuration. It includes storage account information and supports
    Azure-specific triggers like HTTP triggers.

    Attributes:
        function_storage: Azure Storage account used for function code storage
    """

    def __init__(
        self,
        name: str,
        benchmark: str,
        code_hash: str,
        function_storage: AzureResources.Storage,
        cfg: FunctionConfig,
    ) -> None:
        """Initialize Azure Function.

        Args:
            name: Name of the Azure Function
            benchmark: Name of the benchmark this function implements
            code_hash: Hash of the function code for caching
            function_storage: Azure Storage account for function code
            cfg: Function configuration with memory, timeout, etc.
        """
        super().__init__(benchmark, name, code_hash, cfg)
        self.function_storage = function_storage

    def serialize(self) -> dict:
        """Serialize function to dictionary.

        Returns:
            Dictionary containing function data including Azure-specific storage.
        """
        return {
            **super().serialize(),
            "function_storage": self.function_storage.serialize(),
        }

    @staticmethod
    def deserialize(cached_config: dict) -> Function:
        """Deserialize function from cached configuration.

        Recreates an AzureFunction instance from cached data including
        function configuration, storage account, and triggers.

        Args:
            cached_config: Dictionary containing cached function data

        Returns:
            AzureFunction instance with restored configuration.

        Raises:
            AssertionError: If unknown trigger type is encountered.
        """
        cfg = FunctionConfig.deserialize(cached_config["config"])
        ret = AzureFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["hash"],
            AzureResources.Storage.deserialize(cached_config["function_storage"]),
            cfg,
        )
        from sebs.azure.triggers import HTTPTrigger

        for trigger in cached_config["triggers"]:
            trigger_type = {"HTTP": HTTPTrigger}.get(trigger["type"])
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

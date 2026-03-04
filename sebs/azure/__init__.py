"""Azure integration package for SeBS benchmarking.

This package provides comprehensive Azure integration for the Serverless
Benchmarking Suite (SeBS). It includes all necessary components for deploying,
managing, and benchmarking serverless functions on Microsoft Azure.

Main Components:
    Azure: Main system class for Azure platform integration
    AzureFunction: Azure Function representation and management
    AzureConfig: Configuration management for Azure credentials and resources
    BlobStorage: Azure Blob Storage integration for data management

The package handles:
    - Azure Functions deployment and lifecycle management
    - Azure Storage integration for benchmark data
    - CosmosDB support for NoSQL benchmarks
    - Resource group and subscription management
    - Azure CLI integration via Docker containers
    - Performance metrics collection via Application Insights

Example:
    Basic usage for Azure benchmarking:
    ::

        from sebs.azure import Azure, AzureConfig

        # Load configuration
        config = AzureConfig.deserialize(config_dict, cache, handlers)

        # Initialize Azure system
        azure = Azure(sebs_config, config, cache, docker_client, handlers)
        azure.initialize()

        # Deploy and benchmark functions
        function = azure.create_function(code_package, func_name, False, "")
        result = function.invoke(payload)
"""

from .azure import Azure  # noqa
from .function import AzureFunction  # noqa
from .config import AzureConfig  # noqa
from .blob_storage import BlobStorage  # noqa

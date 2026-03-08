"""Apache OpenWhisk integration module for SeBS.

This module provides the complete OpenWhisk integration:
- OpenWhisk system and function management
- Configuration classes for credentials and resources
- Function and trigger implementations
- Docker container management
- CLI and HTTP-based invocation methods

Main Classes:
    OpenWhisk: Main OpenWhisk system implementation
    OpenWhiskConfig: Configuration management for OpenWhisk deployments
    OpenWhiskFunction: OpenWhisk-specific function implementation
    LibraryTrigger: CLI-based function invocation
    HTTPTrigger: HTTP-based function invocation

Example:
    >>> from sebs.openwhisk import OpenWhisk, OpenWhiskConfig
    >>> config = OpenWhiskConfig.deserialize(config_dict, cache, handlers)
    >>> system = OpenWhisk(sys_config, config, cache, docker_client, handlers)
"""

from .openwhisk import OpenWhisk  # noqa
from .config import OpenWhiskConfig  # noqa

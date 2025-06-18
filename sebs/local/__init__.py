"""SeBS local execution platform module.

This module provides the local execution platform for the Serverless Benchmarking Suite.
It enables running serverless functions locally using Docker containers, providing a
development and testing environment that mimics serverless execution without requiring
cloud platform deployment.

Key components:
- Local: Main system class for local function execution
- LocalFunction: Represents a function deployed locally in a Docker container
- Deployment: Manages deployments and memory measurements for local functions

The local platform supports HTTP triggers and provides memory profiling capabilities
for performance analysis.
"""

from .local import Local  # noqa
from .function import LocalFunction  # noqa
from .deployment import Deployment  # noqa

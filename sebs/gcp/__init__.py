"""Google Cloud Platform (GCP) integration for SeBS.

This package provides comprehensive Google Cloud Platform support for the
Serverless Benchmarking Suite, including Cloud Functions deployment, Cloud Storage
for object storage, Firestore/Datastore for NoSQL operations, and Cloud Monitoring
for performance metrics collection.

The package includes:
- Function deployment and management via Cloud Functions API
- Object storage through Google Cloud Storage buckets
- NoSQL database operations using Firestore in Datastore mode
- Performance monitoring via Cloud Monitoring and Cloud Logging
- Docker-based gcloud CLI integration for administrative operations
- Comprehensive credential and resource management

Modules:
    gcp: Main GCP system implementation
    config: Configuration and credential management
    storage: Cloud Storage integration
    function: Cloud Function representation
    triggers: Function invocation triggers
    datastore: Firestore/Datastore NoSQL implementation
    resources: System resource management
    cli: gcloud CLI integration

Example:
    Basic GCP system setup:

        from sebs.gcp import GCP, GCPConfig

        # Configure GCP with credentials
        config = GCPConfig.deserialize(config_dict, cache, handlers)

        # Initialize GCP system
        gcp_system = GCP(system_config, config, cache, docker_client, handlers)
        gcp_system.initialize()

        # Deploy a function
        function = gcp_system.create_function(benchmark, "my-function", False, "")
"""

from .gcp import GCP  # noqa
from .config import GCPConfig  # noqa
from .storage import GCPStorage  # noqa
from .function import GCPFunction  # noqa

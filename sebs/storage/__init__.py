"""Storage module for the Serverless Benchmarking Suite (SeBS).

This module provides storage abstractions and implementations for SeBS, supporting
both object storage (S3-compatible) and NoSQL database storage. It includes:

- Configuration classes for different storage backends
- MinIO implementation for local S3-compatible object storage
- ScyllaDB implementation for local DynamoDB-compatible NoSQL storage
- Resource management classes for self-hosted storage deployments

The storage module enables benchmarks to work with persistent data storage
across different deployment environments while maintaining consistent interfaces.

Key Components:
    - config: Configuration dataclasses for storage backends
    - minio: MinIO-based object storage implementation
    - scylladb: ScyllaDB-based NoSQL storage implementation
    - resources: Resource management for self-hosted storage deployments

Example:
    To use MinIO object storage in a benchmark:

    ```python
    from sebs.storage.minio import Minio
    from sebs.storage.config import MinioConfig

    # Configure and start MinIO
    config = MinioConfig(mapped_port=9000, version="latest")
    storage = Minio(docker_client, cache_client, resources, False)
    storage.config = config
    storage.start()
    ```
"""

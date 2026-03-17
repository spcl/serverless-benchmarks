# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Type definitions for the Serverless Benchmarking Suite.

This module provides enum types used throughout the benchmarking suite
to represent different platforms, storage types, and benchmark modules.
These types are used for configuration, deployment, and resource management.
"""

from __future__ import annotations
from enum import Enum


class BenchmarkModule(str, Enum):
    """Types of benchmark modules.

    Benchmark modules indicate which additional packages and configuration
    are needed for the benchmark to work correctly.

    - STORAGE: Object storage module for storing and retrieving files
    """

    STORAGE = "storage"
    NOSQL = "nosql"


class Platforms(str, Enum):
    """Supported serverless platforms.

    This enum defines the different serverless platforms supported by
    the benchmarking suite:

    - AWS: Amazon Web Services Lambda
    - AZURE: Microsoft Azure Functions
    - GCP: Google Cloud Platform Cloud Functions
    - LOCAL: Local execution environment
    - OPENWHISK: Apache OpenWhisk
    """

    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    LOCAL = "local"
    OPENWHISK = "openwhisk"


class Storage(str, Enum):
    """Supported object storage services.

    This enum defines the different object storage services supported
    by the benchmarking suite:

    - AWS_S3: Amazon Simple Storage Service (S3)
    - AZURE_BLOB_STORAGE: Microsoft Azure Blob Storage
    - GCP_STORAGE: Google Cloud Storage
    - MINIO: MinIO object storage (local or self-hosted)
    """

    AWS_S3 = "aws-s3"
    AZURE_BLOB_STORAGE = "azure-blob-storage"
    GCP_STORAGE = "google-cloud-storage"
    MINIO = "minio"


class Language(str, Enum):
    """
    Enumeration of supported programming languages.

    Currently supports Python, Node.js, and C++ for serverless functions.
    """

    PYTHON = "python"
    NODEJS = "nodejs"
    CPP = "cpp"
    JAVA = "java"

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

    def __str__(self) -> str:
        """String serialization"""
        return self.value


class NoSQLStorage(str, Enum):
    """Supported NoSQL database services.

    This enum defines the different NoSQL database services supported
    by the benchmarking suite:

    - AWS_DYNAMODB: Amazon DynamoDB
    - AZURE_COSMOSDB: Microsoft Azure Cosmos DB
    - GCP_DATASTORE: Google Cloud Datastore
    - SCYLLADB: ScyllaDB (compatible with Apache Cassandra)
    """

    AWS_DYNAMODB = "aws-dynamodb"
    AZURE_COSMOSDB = "azure-cosmosdb"
    GCP_DATASTORE = "google-cloud-datastore"
    SCYLLADB = "scylladb"


class Architecture(str, Enum):
    """
    Defines the CPU architectures that can be targeted for function deployment.
    """

    X86 = "x64"
    ARM = "arm64"

    def serialize(self) -> str:
        """
        Returns:
            str: String representation of the architecture
        """
        return self.value

    @staticmethod
    def deserialize(val: str) -> Architecture:
        """
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

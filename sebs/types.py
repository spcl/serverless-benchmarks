"""Type definitions for the Serverless Benchmarking Suite.

This module provides enum types used throughout the benchmarking suite
to represent different platforms, storage types, and benchmark modules.
These types are used for configuration, deployment, and resource management.
"""

from enum import Enum


class BenchmarkModule(str, Enum):
    """Types of benchmark modules.
    
    This enum defines the different types of benchmark modules that can
    be used by benchmark functions:
    
    - STORAGE: Object storage module for storing and retrieving files
    - NOSQL: NoSQL database module for storing and retrieving structured data
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

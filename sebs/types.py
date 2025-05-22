from enum import Enum


class BenchmarkModule(str, Enum):
    """
    Enumeration of SeBS modules that benchmarks can utilize.
    These modules typically provide access to specific types of cloud resources.
    """
    STORAGE = "storage" #: Represents object storage services (e.g., S3, Minio).
    NOSQL = "nosql"     #: Represents NoSQL database services (e.g., DynamoDB, ScyllaDB).


class Platforms(str, Enum):
    """
    Enumeration of supported FaaS platforms in SeBS.
    """
    AWS = "aws" #: Amazon Web Services
    AZURE = "azure" #: Microsoft Azure
    GCP = "gcp" #: Google Cloud Platform
    LOCAL = "local" #: Local Docker-based deployment for testing.
    OPENWHISK = "openwhisk" #: Apache OpenWhisk


class Storage(str, Enum):
    """
    Enumeration of specific persistent object storage service types supported by SeBS.
    """
    AWS_S3 = "aws-s3" #: AWS Simple Storage Service (S3).
    AZURE_BLOB_STORAGE = "azure-blob-storage" #: Azure Blob Storage.
    GCP_STORAGE = "google-cloud-storage" #: Google Cloud Storage.
    MINIO = "minio" #: Self-hosted Minio S3-compatible storage.


class NoSQLStorage(str, Enum):
    """
    Enumeration of specific NoSQL database service types supported by SeBS.
    """
    AWS_DYNAMODB = "aws-dynamodb" #: AWS DynamoDB.
    AZURE_COSMOSDB = "azure-cosmosdb" #: Azure Cosmos DB.
    GCP_DATASTORE = "google-cloud-datastore" #: Google Cloud Datastore (Firestore in Datastore mode).
    SCYLLADB = "scylladb" #: Self-hosted ScyllaDB (DynamoDB compatible via Alternator).

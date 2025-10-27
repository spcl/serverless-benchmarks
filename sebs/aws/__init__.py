"""AWS module for the Serverless Benchmarking Suite (SeBS).

This module provides the AWS implementation of the SeBS framework, enabling
deployment and management of serverless functions on AWS Lambda. It includes
comprehensive support for AWS services including Lambda, S3, DynamoDB, ECR,
and API Gateway.

Key components:
    AWS: Main AWS system implementation
    LambdaFunction: AWS Lambda function representation
    AWSConfig: AWS-specific configuration management
    S3: Object storage implementation for S3
    DynamoDB: Key-value store implementation for DynamoDB

The module handles AWS-specific functionality including:
- Lambda function deployment and management
- Container deployments via ECR
- S3 storage for code packages and data
- DynamoDB NoSQL storage
- API Gateway HTTP triggers
- IAM role management
- CloudWatch metrics collection
"""

from .aws import AWS, LambdaFunction  # noqa
from .config import AWSConfig  # noqa
from .s3 import S3  # noqa

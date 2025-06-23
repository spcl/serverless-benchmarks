"""
Module for AWS Lambda function implementation in the SeBs framework.

This module provides the LambdaFunction class, which represents an AWS Lambda
function in the serverless benchmarking suite. It handles AWS-specific attributes
and operations such as ARN, runtime, role, and serialization.
"""

from typing import cast, Optional

from sebs.aws.s3 import S3
from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig


class LambdaFunction(Function):
    """
    AWS Lambda function implementation for the SeBs framework.

    This class represents an AWS Lambda function in the serverless benchmarking
    suite. It extends the base Function class with AWS-specific attributes and
    functionality.

    Attributes:
        arn: Amazon Resource Name of the Lambda function
        role: IAM role ARN used by the function
        runtime: Runtime environment for the function (e.g., 'python3.8')
        bucket: S3 bucket name where the function code is stored
    """

    def __init__(
        self,
        name: str,
        benchmark: str,
        arn: str,
        code_package_hash: str,
        runtime: str,
        role: str,
        cfg: FunctionConfig,
        bucket: Optional[str] = None,
    ):
        """
        Initialize an AWS Lambda function.

        Args:
            name: Name of the function
            benchmark: Name of the benchmark
            arn: Amazon Resource Name of the Lambda function
            code_package_hash: Hash of the code package
            runtime: Runtime environment for the function
            role: IAM role ARN used by the function
            cfg: Function configuration
            bucket: S3 bucket name where the function code is stored
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.arn = arn
        self.role = role
        self.runtime = runtime
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        """
        Get the type name of this class.

        Returns:
            str: The type name
        """
        return "AWS.LambdaFunction"

    def serialize(self) -> dict:
        """
        Serialize the Lambda function to a dictionary.

        Returns:
            dict: Dictionary representation of the Lambda function
        """
        return {
            **super().serialize(),
            "arn": self.arn,
            "runtime": self.runtime,
            "role": self.role,
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "LambdaFunction":
        """
        Create a LambdaFunction instance from a cached configuration.

        Args:
            cached_config: Dictionary containing the cached function configuration

        Returns:
            LambdaFunction: A new instance with the deserialized data

        Raises:
            AssertionError: If an unknown trigger type is encountered
        """
        from sebs.faas.function import Trigger
        from sebs.aws.triggers import LibraryTrigger, HTTPTrigger

        cfg = FunctionConfig.deserialize(cached_config["config"])
        ret = LambdaFunction(
            cached_config["name"],
            cached_config["benchmark"],
            cached_config["arn"],
            cached_config["hash"],
            cached_config["runtime"],
            cached_config["role"],
            cfg,
            cached_config["bucket"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": LibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

    def code_bucket(self, benchmark: str, storage_client: S3) -> str:
        """
        Get the S3 bucket for the function code.

        Args:
            benchmark: Name of the benchmark
            storage_client: S3 storage client

        Returns:
            str: Name of the S3 bucket
        """
        self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket

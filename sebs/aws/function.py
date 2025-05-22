from typing import cast, Optional

from sebs.aws.s3 import S3
from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig


class LambdaFunction(Function):
    """
    Represents an AWS Lambda function.

    Extends the base Function class with AWS-specific attributes like ARN, role,
    and S3 bucket for code deployment.
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
        Initialize a LambdaFunction instance.

        :param name: Name of the Lambda function.
        :param benchmark: Name of the benchmark this function belongs to.
        :param arn: Amazon Resource Name (ARN) of the Lambda function.
        :param code_package_hash: Hash of the deployed code package.
        :param runtime: AWS Lambda runtime identifier (e.g., "python3.8").
        :param role: IAM role ARN assumed by the Lambda function.
        :param cfg: FunctionConfig object with memory, timeout, etc.
        :param bucket: Optional S3 bucket name where the code package is stored (for large functions).
        """
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.arn = arn
        self.role = role
        self.runtime = runtime
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        """Return the type name of this function implementation."""
        return "AWS.LambdaFunction"

    def serialize(self) -> dict:
        """
        Serialize the LambdaFunction instance to a dictionary.

        Includes AWS-specific attributes along with base Function attributes.

        :return: Dictionary representation of the LambdaFunction.
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
        Deserialize a LambdaFunction instance from a dictionary.

        Typically used when loading function details from a cache.

        :param cached_config: Dictionary containing serialized LambdaFunction data.
        :return: A new LambdaFunction instance.
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
        Get or assign the S3 bucket for code deployment.

        If a bucket is not already assigned to this function, it retrieves
        the deployment bucket from the S3 storage client.

        :param benchmark: Name of the benchmark (used by storage_client if creating a new bucket, though typically not needed here).
        :param storage_client: S3 client instance.
        :return: The name of the S3 bucket used for code deployment.
        """
        self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket

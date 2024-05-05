from typing import cast, Optional

from sebs.aws.s3 import S3
from sebs.faas.config import Resources
from sebs.faas.function import Function, FunctionConfig


class LambdaFunction(Function):
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
        super().__init__(benchmark, name, code_package_hash, cfg)
        self.arn = arn
        self.role = role
        self.runtime = runtime
        self.bucket = bucket

    @staticmethod
    def typename() -> str:
        return "AWS.LambdaFunction"

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "arn": self.arn,
            "runtime": self.runtime,
            "role": self.role,
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "LambdaFunction":
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

    def code_bucket(self, benchmark: str, storage_client: S3):
        self.bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        return self.bucket

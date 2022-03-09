from typing import cast, Optional, List

from sebs.aws.s3 import S3
from sebs.aws.function import LambdaFunction
from sebs.faas.workflow import Workflow


class SFNWorkflow(Workflow):
    def __init__(
        self,
        name: str,
        functions: List[LambdaFunction],
        benchmark: str,
        arn: str,
        code_package_hash: str,
        role: str
    ):
        super().__init__(benchmark, name, code_package_hash)
        self.functions = functions
        self.arn = arn
        self.role = role

    @staticmethod
    def typename() -> str:
        return "AWS.SFNWorkflow"

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "functions": self.functions,
            "arn": self.arn,
            "role": self.role
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "SFNWorkflow":
        from sebs.faas.function import Trigger
        from sebs.aws.triggers import WorkflowLibraryTrigger, HTTPTrigger

        ret = LambdaWorkflow(
            cached_config["name"],
            cached_config["functions"],
            cached_config["hash"],
            cached_config["arn"],
            cached_config["role"]
        )
        for trigger in cached_config["triggers"]:
            trigger_type = cast(
                Trigger,
                {"Library": WorkflowLibraryTrigger, "HTTP": HTTPTrigger}.get(trigger["type"]),
            )
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

    def code_bucket(self, benchmark: str, storage_client: S3):
        self.bucket, idx = storage_client.add_input_bucket(benchmark)
        return self.bucket

from typing import Optional

from sebs.aws.s3 import S3
from sebs.faas.function import Function


class LambdaFunction(Function):
    def __init__(
        self,
        name: str,
        code_package_hash: str,
        timeout: int,
        memory: int,
        runtime: str,
        role: str,
        bucket: Optional[str] = None,
    ):
        super().__init__(name, code_package_hash)
        self.timeout = timeout
        self.memory = memory
        self.runtime = runtime
        self.role = role
        self.bucket = bucket
        self._updated_code = False

    @property
    def updated_code(self) -> bool:
        return self._updated_code

    @updated_code.setter
    def updated_code(self, val: bool):
        self._updated_code = val

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "timeout": self.timeout,
            "memory": self.memory,
            "runtime": self.runtime,
            "role": self.role,
            "bucket": self.bucket,
        }

    @staticmethod
    def deserialize(cached_config: dict) -> "LambdaFunction":
        from sebs.aws.triggers import LibraryTrigger

        ret = LambdaFunction(
            cached_config["name"],
            cached_config["hash"],
            cached_config["timeout"],
            cached_config["memory"],
            cached_config["runtime"],
            cached_config["role"],
            cached_config["bucket"],
        )
        for trigger in cached_config["triggers"]:
            trigger_type = {"Library": LibraryTrigger}.get(trigger["type"])
            assert trigger_type, "Unknown trigger type {}".format(trigger["type"])
            ret.add_trigger(trigger_type.deserialize(trigger))
        return ret

    def code_bucket(self, benchmark: str, storage_client: S3):
        self.bucket, idx = storage_client.add_input_bucket(benchmark)

import json
import os
import time
from typing import cast

import boto3


from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources


class AWSCredentials(Credentials):

    _access_key: str
    _secret_key: str

    def __init__(self, access_key: str, secret_key: str):
        super().__init__()
        self._access_key = access_key
        self._secret_key = secret_key

    @staticmethod
    def typename() -> str:
        return "AWS.Credentials"

    @property
    def access_key(self) -> str:
        return self._access_key

    @property
    def secret_key(self) -> str:
        return self._secret_key

    @staticmethod
    def deserialize(dct: dict) -> Credentials:
        return AWSCredentials(dct["access_key"], dct["secret_key"])

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Credentials:

        # FIXME: update return types of both functions to avoid cast
        # needs 3.7+  to support annotations
        cached_config = cache.get_config("aws")
        ret: AWSCredentials
        # Load cached values
        if cached_config and "credentials" in cached_config:
            ret = cast(
                AWSCredentials, AWSCredentials.deserialize(cached_config["credentials"])
            )
            ret.logging.info("Using cached credentials for AWS")
        else:
            # Check for new config
            if "credentials" in config:
                ret = cast(
                    AWSCredentials, AWSCredentials.deserialize(config["credentials"])
                )
            elif "AWS_ACCESS_KEY_ID" in os.environ:
                ret = AWSCredentials(
                    os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"]
                )
            else:
                raise RuntimeError(
                    "AWS login credentials are missing! Please set "
                    "up environmental variables AWS_ACCESS_KEY_ID and "
                    "AWS_SECRET_ACCESS_KEY"
                )
            ret.logging.info("No cached credentials for AWS found, initialize!")
        return ret

    def update_cache(self, cache: Cache):
        cache.update_config(
            val=self.access_key, keys=["aws", "credentials", "access_key"]
        )
        cache.update_config(
            val=self.secret_key, keys=["aws", "credentials", "secret_key"]
        )

    def serialize(self) -> dict:
        out = {"access_key": self.access_key, "secret_key": self.secret_key}
        return out


class AWSResources(Resources):
    def __init__(self, lambda_role: str):
        super().__init__()
        self._lambda_role = lambda_role

    @staticmethod
    def typename() -> str:
        return "AWS.Resources"

    def lambda_role(self, boto3_session: boto3.session.Session) -> str:
        if not self._lambda_role:
            iam_client = boto3_session.client(service_name="iam")
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
            role_name = "sebs-lambda-role"
            attached_policies = [
                "arn:aws:iam::aws:policy/AmazonS3FullAccess",
                "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            ]
            try:
                out = iam_client.get_role(RoleName=role_name)
                self._lambda_role = out["Role"]["Arn"]
                self.logging.info(f"AWS: Selected {self._lambda_role} IAM role")
            except iam_client.exceptions.NoSuchEntityException:
                out = iam_client.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                )
                self._lambda_role = out["Role"]["Arn"]
                self.logging.info(
                    f"AWS: Created {self._lambda_role} IAM role. "
                    "Sleep 10 seconds to avoid problems when using role immediately."
                )
                time.sleep(10)
            # Attach basic AWS Lambda and S3 policies.
            for policy in attached_policies:
                iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy)
        return self._lambda_role

    # FIXME: python3.7+ future annotatons
    @staticmethod
    def deserialize(dct: dict) -> Resources:
        return AWSResources(dct["lambda-role"] if "lambda-role" in dct else "")

    def serialize(self) -> dict:
        out = {"lambda-role": self._lambda_role}
        return out

    def update_cache(self, cache: Cache):
        cache.update_config(
            val=self._lambda_role, keys=["aws", "resources", "lambda-role"]
        )

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Resources:

        cached_config = cache.get_config("aws")
        ret: AWSResources
        # Load cached values
        if cached_config and "resources" in cached_config:
            ret = cast(
                AWSResources, AWSResources.deserialize(cached_config["resources"])
            )
            ret.logging.info("Using cached resources for AWS")
        else:
            # Check for new config
            if "resources" in config:
                ret = cast(AWSResources, AWSResources.deserialize(config["resources"]))
                ret.logging.info(
                    "No cached resources for AWS found, using user configuration."
                )
            else:
                ret = AWSResources(lambda_role="")
                ret.logging.info("No resources for AWS found, initialize!")

        return ret


class AWSConfig(Config):
    def __init__(self, credentials: AWSCredentials, resources: AWSResources):
        super().__init__()
        self._credentials = credentials
        self._resources = resources

    @staticmethod
    def typename() -> str:
        return "AWS.Config"

    @property
    def credentials(self) -> AWSCredentials:
        return self._credentials

    @property
    def resources(self) -> AWSResources:
        return self._resources

    # FIXME: use future annotations (see sebs/faas/system)
    @staticmethod
    def deserialize(cfg: Config, dct: dict):
        config = cast(AWSConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def initialize(config: dict, cache: Cache) -> Config:

        cached_config = cache.get_config("aws")
        # FIXME: use future annotations (see sebs/faas/system)
        credentials = cast(AWSCredentials, AWSCredentials.initialize(config, cache))
        resources = cast(AWSResources, AWSResources.initialize(config, cache))
        config_obj = AWSConfig(credentials, resources)
        # Load cached values
        if cached_config:
            config_obj.logging.info("Using cached config for AWS")
            AWSConfig.deserialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for AWS")
            AWSConfig.deserialize(config_obj, config)

        return config_obj

    """
        Update the contents of the user cache.
        The changes are directly written to the file system.

        Update values: region.
    """

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.region, keys=["aws", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        out = {
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

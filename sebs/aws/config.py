import base64
import json
import os
import time
from typing import cast, Dict, Optional, Tuple

import boto3
from mypy_boto3_ecr import ECRClient

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.aws.function import LambdaFunction
from sebs.utils import LoggingHandlers


class AWSCredentials(Credentials):
    def __init__(self, access_key: str, secret_key: str):
        super().__init__()

        self._access_key = access_key
        self._secret_key = secret_key

        client = boto3.client(
            "sts", aws_access_key_id=self.access_key, aws_secret_access_key=self.secret_key
        )
        self._account_id = client.get_caller_identity()["Account"]

    @staticmethod
    def typename() -> str:
        return "AWS.Credentials"

    @property
    def access_key(self) -> str:
        return self._access_key

    @property
    def secret_key(self) -> str:
        return self._secret_key

    @property
    def account_id(self) -> str:
        return self._account_id

    @staticmethod
    def initialize(dct: dict) -> "AWSCredentials":
        return AWSCredentials(dct["access_key"], dct["secret_key"])

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:

        # FIXME: update return types of both functions to avoid cast
        # needs 3.7+  to support annotations
        cached_config = cache.get_config("aws")
        ret: AWSCredentials
        account_id: Optional[str] = None

        # Load cached values
        if cached_config and "credentials" in cached_config:
            account_id = cached_config["credentials"]["account_id"]

        # Check for new config.
        # Loading old results might result in not having credentials in the JSON - need to check.
        if "credentials" in config and "access_key" in config["credentials"]:
            ret = AWSCredentials.initialize(config["credentials"])
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

        if account_id is not None and account_id != ret.account_id:
            ret.logging.error(
                f"The account id {ret.account_id} from provided credentials is different "
                f"from the account id {account_id} found in the cache! Please change "
                "your cache directory or create a new one!"
            )
            raise RuntimeError(
                f"AWS login credentials do not match the account {account_id} in cache!"
            )
        ret.logging_handlers = handlers
        return ret

    def update_cache(self, cache: Cache):
        cache.update_config(val=self.account_id, keys=["aws", "credentials", "account_id"])

    def serialize(self) -> dict:
        out = {"account_id": self._account_id}
        return out


class AWSResources(Resources):
    class HTTPApi:
        def __init__(self, arn: str, endpoint: str):
            self._arn = arn
            self._endpoint = endpoint

        @property
        def arn(self) -> str:
            return self._arn

        @property
        def endpoint(self) -> str:
            return self._endpoint

        @staticmethod
        def deserialize(dct: dict) -> "AWSResources.HTTPApi":
            return AWSResources.HTTPApi(dct["arn"], dct["endpoint"])

        def serialize(self) -> dict:
            out = {"arn": self.arn, "endpoint": self.endpoint}
            return out

    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        super().__init__(name="aws")
        self._docker_registry: Optional[str] = registry if registry != "" else None
        self._docker_username: Optional[str] = username if username != "" else None
        self._docker_password: Optional[str] = password if password != "" else None
        self._container_repository: Optional[str] = None
        self._lambda_role = ""
        self._http_apis: Dict[str, AWSResources.HTTPApi] = {}

    @staticmethod
    def typename() -> str:
        return "AWS.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        return self._docker_password

    @property
    def container_repository(self) -> Optional[str]:
        return self._container_repository

    def lambda_role(self, boto3_session: boto3.session.Session) -> str:
        if not self._lambda_role:
            iam_client = boto3_session.client(service_name="iam")
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "",
                        "Effect": "Allow",
                        "Principal": {"Service": ["lambda.amazonaws.com", "states.amazonaws.com"]},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
            role_name = "sebs-role"
            attached_policies = [
                "arn:aws:iam::aws:policy/AmazonS3FullAccess",
                "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
                "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                "arn:aws:iam::aws:policy/service-role/AWSLambdaRole",
                "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess",
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

    def http_api(
        self, api_name: str, func: LambdaFunction, boto3_session: boto3.session.Session
    ) -> "AWSResources.HTTPApi":

        http_api = self._http_apis.get(api_name)
        if not http_api:
            # get apigateway client
            api_client = boto3_session.client(
                service_name="apigatewayv2", region_name=cast(str, self._region)
            )

            # check existing apis
            api_data = None
            for api in api_client.get_apis()["Items"]:
                if api["Name"] == api_name:
                    self.logging.info(f"Using existing HTTP API {api_name}")
                    api_data = api
                    break
            if not api_data:
                self.logging.info(f"Creating HTTP API {api_name}")

                retries = 0
                while retries < 5:

                    try:
                        api_data = api_client.create_api(  # type: ignore
                            Name=api_name, ProtocolType="HTTP", Target=func.arn
                        )
                        break
                    except api_client.exceptions.TooManyRequestsException as e:

                        retries += 1

                        if retries == 5:
                            self.logging.error("Failed to create the HTTP API!")
                            self.logging.error(e)
                            raise RuntimeError("Failed to create the HTTP API!")
                        else:
                            self.logging.info("HTTP API is overloaded, applying backoff.")
                            time.sleep(retries)

            api_id = api_data["ApiId"]  # type: ignore
            endpoint = api_data["ApiEndpoint"]  # type: ignore

            # function's arn format is: arn:aws:{region}:{account-id}:{func}
            # easier than querying AWS resources to get account id
            account_id = func.arn.split(":")[4]
            # API arn is:
            arn = f"arn:aws:execute-api:{self._region}:{account_id}:{api_id}"
            http_api = AWSResources.HTTPApi(arn, endpoint)
            self._http_apis[api_name] = http_api
        else:
            self.logging.info(f"Using cached HTTP API {api_name}")
        return http_api

    def check_ecr_repository_exists(
        self, ecr_client: ECRClient, repository_name: str
    ) -> Optional[str]:
        try:
            resp = ecr_client.describe_repositories(repositoryNames=[repository_name])
            return resp["repositories"][0]["repositoryUri"]
        except ecr_client.exceptions.RepositoryNotFoundException:
            return None
        except Exception as e:
            self.logging.error(f"Error checking repository: {e}")
            raise e

    def get_ecr_repository(self, ecr_client: ECRClient) -> str:

        if self._container_repository is not None:
            return self._container_repository

        self._container_repository = "sebs-benchmarks-{}".format(self._resources_id)

        self._docker_registry = self.check_ecr_repository_exists(
            ecr_client, self._container_repository
        )

        if self._docker_registry is None:
            try:
                resp = ecr_client.create_repository(repositoryName=self._container_repository)
                self.logging.info(f"Created ECR repository: {self._container_repository}")

                self._docker_registry = resp["repository"]["repositoryUri"]
            except ecr_client.exceptions.RepositoryAlreadyExistsException:
                # Support the situation where two invocations concurrently initialize it.
                self.logging.info(f"ECR repository {self._container_repository} already exists.")
                self._docker_registry = self.check_ecr_repository_exists(
                    ecr_client, self._container_repository
                )

        return self._container_repository

    def ecr_repository_authorization(self, ecr_client: ECRClient) -> Tuple[str, str, str]:

        if self._docker_password is None:
            response = ecr_client.get_authorization_token()
            auth_token = response["authorizationData"][0]["authorizationToken"]
            decoded_token = base64.b64decode(auth_token).decode("utf-8")
            # Split username:password
            self._docker_username, self._docker_password = decoded_token.split(":")

        assert self._docker_username is not None
        assert self._docker_registry is not None

        return self._docker_username, self._docker_password, self._docker_registry

    @staticmethod
    def initialize(res: Resources, dct: dict):

        ret = cast(AWSResources, res)
        super(AWSResources, AWSResources).initialize(ret, dct)

        if "docker" in dct:
            ret._docker_registry = dct["docker"]["registry"]
            ret._docker_username = dct["docker"]["username"]
            ret._container_repository = dct["container_repository"]

        ret._lambda_role = dct["lambda-role"] if "lambda-role" in dct else ""
        if "http-apis" in dct:
            for key, value in dct["http-apis"].items():
                ret._http_apis[key] = AWSResources.HTTPApi.deserialize(value)

        return ret

    def serialize(self) -> dict:
        out = {
            **super().serialize(),
            "lambda-role": self._lambda_role,
            "http-apis": {key: value.serialize() for (key, value) in self._http_apis.items()},
            "docker": {
                "registry": self.docker_registry,
                "username": self.docker_username,
            },
            "container_repository": self.container_repository,
        }
        return out

    def update_cache(self, cache: Cache):
        super().update_cache_redis(keys=["aws", "resources"], cache=cache)
        super().update_cache(cache)
        cache.update_config(
            val=self.docker_registry, keys=["aws", "resources", "docker", "registry"]
        )
        cache.update_config(
            val=self.docker_username, keys=["aws", "resources", "docker", "username"]
        )
        cache.update_config(
            val=self.container_repository, keys=["aws", "resources", "container_repository"]
        )
        cache.update_config(val=self._lambda_role, keys=["aws", "resources", "lambda-role"])
        for name, api in self._http_apis.items():
            cache.update_config(val=api.serialize(), keys=["aws", "resources", "http-apis", name])

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        ret = AWSResources()
        cached_config = cache.get_config("aws")

        # Load cached values
        if cached_config and "resources" in cached_config:
            AWSResources.initialize(ret, cached_config["resources"])
            ret.load_redis(cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for AWS")
        else:
            # Check for new config
            if "resources" in config:
                AWSResources.initialize(ret, config["resources"])
                ret.load_redis(config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for AWS found, using user configuration.")
            else:
                AWSResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for AWS found, initialize!")

        return ret


class AWSConfig(Config):
    def __init__(self, credentials: AWSCredentials, resources: AWSResources):
        super().__init__(name="aws")
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
    def initialize(cfg: Config, dct: dict):
        config = cast(AWSConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:

        cached_config = cache.get_config("aws")
        # FIXME: use future annotations (see sebs/faas/system)
        credentials = cast(AWSCredentials, AWSCredentials.deserialize(config, cache, handlers))
        resources = cast(AWSResources, AWSResources.deserialize(config, cache, handlers))

        config_obj = AWSConfig(credentials, resources)
        config_obj.logging_handlers = handlers
        # Load cached values
        if cached_config:
            config_obj.logging.info("Using cached config for AWS")
            AWSConfig.initialize(config_obj, cached_config)
        else:
            config_obj.logging.info("Using user-provided config for AWS")
            AWSConfig.initialize(config_obj, config)

        resources.region = config_obj.region
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
            "name": "aws",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

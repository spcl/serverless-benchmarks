"""Configuration management for AWS SeBS integration.

This module provides configuration classes for AWS credentials, resources, and settings
used when deploying to AWS Lambda. It handles
AWS authentication, resource management including ECR repositories, IAM roles, and
HTTP APIs, along with caching and serialization capabilities.

Key classes:
    AWSCredentials: Manages AWS access credentials and account information
    AWSResources: Manages AWS resources like ECR repositories, IAM roles, and HTTP APIs
    AWSConfig: Main configuration container combining credentials and resources
"""

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
    """AWS authentication credentials for SeBS.

    This class manages AWS access credentials including access key, secret key,
    and automatically retrieves the associated AWS account ID through STS.

    Account ID is cached to retain information on which account was the benchmark
    executed. Credentials are not cached.

    Attributes:
        _access_key: AWS access key ID
        _secret_key: AWS secret access key
        _account_id: AWS account ID retrieved via STS
    """

    def __init__(self, access_key: str, secret_key: str) -> None:
        """Initialize AWS credentials.

        Args:
            access_key: AWS access key ID
            secret_key: AWS secret access key

        Raises:
            ClientError: If AWS credentials are invalid or STS call fails
        """
        super().__init__()

        self._access_key = access_key
        self._secret_key = secret_key

        client = boto3.client(
            "sts",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        self._account_id = client.get_caller_identity()["Account"]

    @staticmethod
    def typename() -> str:
        """Get the type name for these credentials.

        Returns:
            str: The type name 'AWS.Credentials'
        """
        return "AWS.Credentials"

    @property
    def access_key(self) -> str:
        """Get the AWS access key ID.

        Returns:
            str: AWS access key ID
        """
        return self._access_key

    @property
    def secret_key(self) -> str:
        """Get the AWS secret access key.

        Returns:
            str: AWS secret access key
        """
        return self._secret_key

    @property
    def account_id(self) -> str:
        """Get the AWS account ID.

        Returns:
            str: AWS account ID
        """
        return self._account_id

    @staticmethod
    def initialize(dct: dict) -> "AWSCredentials":
        """Initialize AWS credentials from a dictionary.

        Args:
            dct: Dictionary containing 'access_key' and 'secret_key'

        Returns:
            AWSCredentials: Initialized credentials object

        Raises:
            KeyError: If required keys are missing from dictionary
        """
        return AWSCredentials(dct["access_key"], dct["secret_key"])

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Credentials:
        """Deserialize AWS credentials from configuration and cache.

        Loads AWS credentials from configuration file, environment variables, or cache.
        Validates that credentials match cached account ID if available.

        Args:
            config: Configuration dictionary that may contain credentials
            cache: Cache instance for retrieving/storing credentials
            handlers: Logging handlers for error reporting

        Returns:
            Credentials: Deserialized AWSCredentials instance

        Raises:
            RuntimeError: If credentials are missing or don't match cached account
        """
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

    def update_cache(self, cache: Cache) -> None:
        """Update the cache with current credentials.

        Args:
            cache: Cache instance to update
        """
        cache.update_config(val=self.account_id, keys=["aws", "credentials", "account_id"])

    def serialize(self) -> dict:
        """Serialize credentials to a dictionary.

        Returns:
            dict: Dictionary containing account_id
        """
        out = {"account_id": self._account_id}
        return out


class AWSResources(Resources):
    """AWS resource management for SeBS.

    This class manages AWS-specific resources including ECR repositories,
    IAM roles, HTTP APIs, and Docker registry configurations. It provides
    methods for creating and managing these resources with caching support.

    Attributes:
        _docker_registry: Docker registry URL (ECR repository URI)
        _docker_username: Docker registry username
        _docker_password: Docker registry password
        _container_repository: ECR repository name
        _lambda_role: IAM role ARN for Lambda execution
        _http_apis: Dictionary of HTTP API configurations
    """

    class HTTPApi:
        """HTTP API configuration for AWS API Gateway.

        Represents an HTTP API resource in AWS API Gateway with its ARN and endpoint.

        Attributes:
            _arn: API Gateway ARN
            _endpoint: API Gateway endpoint URL
        """

        def __init__(self, arn: str, endpoint: str) -> None:
            """Initialize HTTP API configuration.

            Args:
                arn: API Gateway ARN
                endpoint: API Gateway endpoint URL
            """
            self._arn = arn
            self._endpoint = endpoint

        @property
        def arn(self) -> str:
            """Get the API Gateway ARN.

            Returns:
                str: API Gateway ARN
            """
            return self._arn

        @property
        def endpoint(self) -> str:
            """Get the API Gateway endpoint URL.

            Returns:
                str: API Gateway endpoint URL
            """
            return self._endpoint

        @staticmethod
        def deserialize(dct: dict) -> "AWSResources.HTTPApi":
            """Deserialize HTTP API from dictionary.

            Args:
                dct: Dictionary containing 'arn' and 'endpoint'

            Returns:
                AWSResources.HTTPApi: Deserialized HTTP API instance
            """
            return AWSResources.HTTPApi(dct["arn"], dct["endpoint"])

        def serialize(self) -> dict:
            """Serialize HTTP API to dictionary.

            Returns:
                dict: Dictionary containing arn and endpoint
            """
            out = {"arn": self.arn, "endpoint": self.endpoint}
            return out

    def __init__(
        self,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """Initialize AWS resources.

        Args:
            registry: Docker registry URL (ECR repository URI)
            username: Docker registry username
            password: Docker registry password
        """
        super().__init__(name="aws")
        self._docker_registry: Optional[str] = registry if registry != "" else None
        self._docker_username: Optional[str] = username if username != "" else None
        self._docker_password: Optional[str] = password if password != "" else None
        self._container_repository: Optional[str] = None
        self._lambda_role = ""
        self._http_apis: Dict[str, AWSResources.HTTPApi] = {}

    @staticmethod
    def typename() -> str:
        """Get the type name for these resources.

        Returns:
            str: The type name 'AWS.Resources'
        """
        return "AWS.Resources"

    @property
    def docker_registry(self) -> Optional[str]:
        """Get the Docker registry URL.

        Returns:
            Optional[str]: Docker registry URL (ECR repository URI)
        """
        return self._docker_registry

    @property
    def docker_username(self) -> Optional[str]:
        """Get the Docker registry username.

        Returns:
            Optional[str]: Docker registry username
        """
        return self._docker_username

    @property
    def docker_password(self) -> Optional[str]:
        """Get the Docker registry password.

        Returns:
            Optional[str]: Docker registry password
        """
        return self._docker_password

    @property
    def container_repository(self) -> Optional[str]:
        """Get the ECR repository name.

        Returns:
            Optional[str]: ECR repository name
        """
        return self._container_repository

    def lambda_role(self, boto3_session: boto3.session.Session) -> str:
        """Get or create IAM role for Lambda execution.

        Creates a Lambda execution role with S3 and basic execution permissions
        if it doesn't already exist. The role allows Lambda functions to access
        S3 and write CloudWatch logs.

        Args:
            boto3_session: Boto3 session for AWS API calls

        Returns:
            str: Lambda execution role ARN

        Raises:
            ClientError: If IAM operations fail
        """
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

    def http_api(
        self, api_name: str, func: LambdaFunction, boto3_session: boto3.session.Session
    ) -> "AWSResources.HTTPApi":
        """Get or create HTTP API for Lambda function.

        Creates an HTTP API Gateway that routes requests to the specified Lambda function.
        If the API already exists, returns the cached instance.

        Args:
            api_name: Name of the HTTP API
            func: Lambda function to route requests to
            boto3_session: Boto3 session for AWS API calls

        Returns:
            AWSResources.HTTPApi: HTTP API configuration

        Raises:
            RuntimeError: If API creation fails after retries
            TooManyRequestsException: If API Gateway rate limits are exceeded
        """

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
        """Check if ECR repository exists.

        Args:
            ecr_client: ECR client instance
            repository_name: Name of the ECR repository

        Returns:
            Optional[str]: Repository URI if exists, None otherwise

        Raises:
            Exception: If ECR operation fails (other than RepositoryNotFound)
        """
        try:
            resp = ecr_client.describe_repositories(repositoryNames=[repository_name])
            return resp["repositories"][0]["repositoryUri"]
        except ecr_client.exceptions.RepositoryNotFoundException:
            return None
        except Exception as e:
            self.logging.error(f"Error checking repository: {e}")
            raise e

    def get_ecr_repository(self, ecr_client: ECRClient) -> str:
        """Get or create ECR repository for container deployments.

        Creates an ECR repository with a unique name based on the resource ID
        if it doesn't already exist. Updates the docker_registry property.

        Args:
            ecr_client: ECR client instance

        Returns:
            str: ECR repository name

        Raises:
            ClientError: If ECR operations fail
        """

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
        """Get ECR repository authorization credentials.

        Retrieves temporary authorization token from ECR and extracts
        username and password for Docker registry authentication.

        Args:
            ecr_client: ECR client instance

        Returns:
            Tuple[str, str, str]: Username, password, and registry URL

        Raises:
            AssertionError: If username or registry are None
            ClientError: If ECR authorization fails
        """

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
    def initialize(res: Resources, dct: dict) -> None:
        """Initialize AWS resources from dictionary.

        Args:
            res: Base Resources instance to initialize
            dct: Dictionary containing resource configuration

        Returns:
            AWSResources: Initialized AWS resources instance
        """

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

    def serialize(self) -> dict:
        """Serialize AWS resources to dictionary.

        Returns:
            dict: Serialized resource configuration
        """
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

    def update_cache(self, cache: Cache) -> None:
        """Update cache with current resource configuration.

        Args:
            cache: Cache instance to update
        """
        super().update_cache(cache)
        cache.update_config(
            val=self.docker_registry, keys=["aws", "resources", "docker", "registry"]
        )
        cache.update_config(
            val=self.docker_username, keys=["aws", "resources", "docker", "username"]
        )
        cache.update_config(
            val=self.container_repository,
            keys=["aws", "resources", "container_repository"],
        )
        cache.update_config(val=self._lambda_role, keys=["aws", "resources", "lambda-role"])
        for name, api in self._http_apis.items():
            cache.update_config(val=api.serialize(), keys=["aws", "resources", "http-apis", name])

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Resources:
        """Deserialize AWS resources from configuration and cache.

        Args:
            config: Configuration dictionary
            cache: Cache instance for retrieving cached resources
            handlers: Logging handlers for status messages

        Returns:
            Resources: Deserialized AWSResources instance
        """
        ret = AWSResources()
        cached_config = cache.get_config("aws")

        # Load cached values
        if cached_config and "resources" in cached_config:
            AWSResources.initialize(ret, cached_config["resources"])
            ret.logging_handlers = handlers
            ret.logging.info("Using cached resources for AWS")
        else:
            # Check for new config
            if "resources" in config:
                AWSResources.initialize(ret, config["resources"])
                ret.logging_handlers = handlers
                ret.logging.info("No cached resources for AWS found, using user configuration.")
            else:
                AWSResources.initialize(ret, {})
                ret.logging_handlers = handlers
                ret.logging.info("No resources for AWS found, initialize!")

        return ret


class AWSConfig(Config):
    """Main AWS configuration container.

    Combines AWS credentials and resources into a single configuration object
    for use by the AWS SeBS implementation.

    Attributes:
        _credentials: AWS authentication credentials
        _resources: AWS resource management configuration
    """

    def __init__(self, credentials: AWSCredentials, resources: AWSResources) -> None:
        """Initialize AWS configuration.

        Args:
            credentials: AWS authentication credentials
            resources: AWS resource management configuration
        """
        super().__init__(name="aws")
        self._credentials = credentials
        self._resources = resources

    @staticmethod
    def typename() -> str:
        """Get the type name for this configuration.

        Returns:
            str: The type name 'AWS.Config'
        """
        return "AWS.Config"

    @property
    def credentials(self) -> AWSCredentials:
        """Get AWS credentials.

        Returns:
            AWSCredentials: AWS authentication credentials
        """
        return self._credentials

    @property
    def resources(self) -> AWSResources:
        """Get AWS resources configuration.

        Returns:
            AWSResources: AWS resource management configuration
        """
        return self._resources

    @staticmethod
    def initialize(cfg: Config, dct: dict) -> None:
        """Initialize AWS configuration from dictionary.

        Args:
            cfg: Base Config instance to initialize
            dct: Dictionary containing 'region' configuration
        """
        config = cast(AWSConfig, cfg)
        config._region = dct["region"]

    @staticmethod
    def deserialize(config: dict, cache: Cache, handlers: LoggingHandlers) -> Config:
        """Deserialize AWS configuration from config and cache.

        Creates an AWSConfig instance by deserializing credentials and resources,
        then loading region configuration from cache or user-provided config.

        Args:
            config: Configuration dictionary
            cache: Cache instance for retrieving cached configuration
            handlers: Logging handlers for status messages

        Returns:
            Config: Deserialized AWSConfig instance
        """
        cached_config = cache.get_config("aws")
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

    def update_cache(self, cache: Cache) -> None:
        """Update the contents of the user cache.

        The changes are directly written to the file system.
        Updates region, credentials, and resources in the cache.

        Args:
            cache: Cache instance to update
        """
        cache.update_config(val=self.region, keys=["aws", "region"])
        self.credentials.update_cache(cache)
        self.resources.update_cache(cache)

    def serialize(self) -> dict:
        """Serialize AWS configuration to dictionary.

        Returns:
            dict: Serialized configuration including name, region, credentials, and resources
        """
        out = {
            "name": "aws",
            "region": self._region,
            "credentials": self._credentials.serialize(),
            "resources": self._resources.serialize(),
        }
        return out

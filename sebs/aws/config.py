# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
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
from __future__ import annotations

import base64
import json
import os
import time
from enum import Enum
from typing import TYPE_CHECKING, cast, Dict, List, Optional, Tuple

import boto3

if TYPE_CHECKING:
    from mypy_boto3_ecr import ECRClient

from sebs.cache import Cache
from sebs.faas.config import Config, Credentials, Resources
from sebs.aws.function import LambdaFunction
from sebs.utils import LoggingHandlers


class FunctionURLAuthType(Enum):
    """
    Authentication types for AWS Lambda Function URLs.
    - NONE: Public access, no authentication required
    - AWS_IAM: Requires IAM authentication with SigV4 signing
    """

    NONE = "NONE"
    AWS_IAM = "AWS_IAM"

    @staticmethod
    def from_string(value: str) -> "FunctionURLAuthType":
        """Convert string to FunctionURLAuthType enum."""
        try:
            return FunctionURLAuthType(value)
        except ValueError:
            raise ValueError(
                f"Invalid auth type '{value}'. Must be one of: "
                f"{[e.value for e in FunctionURLAuthType]}"
            )


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

    class FunctionURL:
        def __init__(
            self,
            url: str,
            function_name: str,
            auth_type: FunctionURLAuthType = FunctionURLAuthType.NONE,
        ):
            self._url = url
            self._function_name = function_name
            self._auth_type = auth_type

        @property
        def url(self) -> str:
            return self._url

        @property
        def function_name(self) -> str:
            return self._function_name

        @property
        def auth_type(self) -> FunctionURLAuthType:
            return self._auth_type

        @staticmethod
        def deserialize(dct: dict) -> "AWSResources.FunctionURL":
            auth_type_str = dct.get("auth_type", "NONE")
            return AWSResources.FunctionURL(
                dct["url"],
                dct["function_name"],
                FunctionURLAuthType.from_string(auth_type_str),
            )

        def serialize(self) -> dict:
            return {
                "url": self.url,
                "function_name": self.function_name,
                "auth_type": self.auth_type.value,
            }

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
        self._function_urls: Dict[str, AWSResources.FunctionURL] = {}
        self._use_function_url: bool = False
        self._function_url_auth_type: FunctionURLAuthType = FunctionURLAuthType.NONE

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

    @property
    def use_function_url(self) -> bool:
        return self._use_function_url

    @use_function_url.setter
    def use_function_url(self, value: bool):
        self._use_function_url = value

    @property
    def function_url_auth_type(self) -> FunctionURLAuthType:
        return self._function_url_auth_type

    @function_url_auth_type.setter
    def function_url_auth_type(self, value: FunctionURLAuthType):
        if not isinstance(value, FunctionURLAuthType):
            raise TypeError(
                f"function_url_auth_type must be a FunctionURLAuthType enum, got {type(value)}"
            )
        self._function_url_auth_type = value

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

    def cleanup_http_apis(
        self, boto3_session: boto3.session.Session, cache_client: Cache, dry_run: bool = False
    ) -> List[str]:
        """Remove HTTP APIs allocated for HTTP triggers.

        Args:
            boto3_session: boto3 session for AWS API calls
            cache_client: SeBS cache client
            dry_run: when true, skip actual deletion

        Returns:
            list of deleted HTTP API names
        """

        deleted: List[str] = []
        dry_run_tag = "[DRY-RUN] " if dry_run else ""

        api_client = boto3_session.client(
            service_name="apigatewayv2", region_name=cast(str, self._region)
        )

        http_apis = cache_client.get_config_key(["aws", "resources", "http-apis"])
        if http_apis is None:
            return deleted

        for name, http_api in http_apis.items():

            self.logging.info(f"{dry_run_tag}Deleting HTTP API: {name} ({http_api['arn']})")

            if not dry_run:
                # We need to extract the ID
                api_id = http_api["arn"].split(":")[-1]
                api_client.delete_api(ApiId=api_id)
            deleted.append(name)

        if not dry_run:
            for api_name in deleted:
                cache_client.remove_config_key(["aws", "resources", "http-apis", api_name])
                self._http_apis.pop(api_name, None)

        return deleted

    def function_url(
        self, func: LambdaFunction, boto3_session: boto3.session.Session
    ) -> "AWSResources.FunctionURL":
        """
        Create or retrieve a Lambda Function URL for the given function.
        Function URLs provide a simpler alternative to API Gateway without the
        29-second timeout limit.
        """
        cached_url = self._function_urls.get(func.name)
        if cached_url:
            self.logging.info(f"Using cached Function URL for {func.name}")
            return cached_url

        # Check for unsupported auth type before attempting to create
        if self._function_url_auth_type == FunctionURLAuthType.AWS_IAM:
            raise NotImplementedError(
                "AWS_IAM authentication for Function URLs is not yet supported. "
                "SigV4 request signing is required for AWS_IAM auth type. "
                "Please use auth_type='NONE' or implement SigV4 signing."
            )

        lambda_client = boto3_session.client(
            service_name="lambda", region_name=cast(str, self._region)
        )

        try:
            response = lambda_client.get_function_url_config(FunctionName=func.name)
            self.logging.info(f"Using existing Function URL for {func.name}")
            url = response["FunctionUrl"]
            auth_type = FunctionURLAuthType.from_string(response["AuthType"])
        except lambda_client.exceptions.ResourceNotFoundException:
            self.logging.info(f"Creating Function URL for {func.name}")

            auth_type = self._function_url_auth_type

            if auth_type == FunctionURLAuthType.NONE:
                self.logging.warning(
                    f"Creating Function URL with auth_type=NONE for {func.name}. "
                    "WARNING: This function will have unrestricted public access. "
                    "Anyone with the URL can invoke this function."
                )
                try:
                    lambda_client.add_permission(
                        FunctionName=func.name,
                        StatementId="FunctionURLAllowPublicAccess",
                        Action="lambda:InvokeFunctionUrl",
                        Principal="*",
                        FunctionUrlAuthType="NONE",
                    )
                except lambda_client.exceptions.ResourceConflictException:
                    # Permission with this StatementId already exists on the function.
                    # This can happen if the function was previously configured with
                    # a Function URL that was deleted but the permission remained,
                    # or if there's a concurrent creation attempt. Safe to ignore.
                    pass

            retries = 0
            while retries < 5:
                try:
                    response = lambda_client.create_function_url_config(
                        FunctionName=func.name,
                        AuthType=auth_type.value,
                    )
                    break
                except lambda_client.exceptions.ResourceConflictException:
                    # Function URL already exists - can happen if a concurrent process
                    # created it between our check and create, or if there was a race
                    # condition. Retrieve the existing configuration instead.
                    response = lambda_client.get_function_url_config(
                        FunctionName=func.name
                    )
                    break
                except lambda_client.exceptions.TooManyRequestsException as e:
                    # AWS is throttling requests - apply exponential backoff
                    retries += 1
                    if retries == 5:
                        self.logging.error("Failed to create Function URL after 5 retries!")
                        self.logging.exception(e)
                        raise RuntimeError("Failed to create Function URL!") from e
                    else:
                        backoff_seconds = retries
                        self.logging.info(
                            f"Function URL creation rate limited, "
                            f"retrying in {backoff_seconds}s (attempt {retries}/5)..."
                        )
                        time.sleep(backoff_seconds)

            url = response["FunctionUrl"]

        function_url_obj = AWSResources.FunctionURL(url, func.name, auth_type)
        self._function_urls[func.name] = function_url_obj
        return function_url_obj

    def delete_function_url(
        self, function_name: str, boto3_session: boto3.session.Session
    ) -> bool:
        """
        Delete a Lambda Function URL for the given function.
        Returns True if deleted successfully, False if it didn't exist.
        """
        lambda_client = boto3_session.client(
            service_name="lambda", region_name=cast(str, self._region)
        )

        # Check if we have cached info about the auth type
        cached_url = self._function_urls.get(function_name)
        cached_auth_type = cached_url.auth_type if cached_url else None

        try:
            lambda_client.delete_function_url_config(FunctionName=function_name)
            self.logging.info(f"Deleted Function URL for {function_name}")

            # Only remove the public access permission if auth_type was NONE
            # (AWS_IAM auth type doesn't create this permission)
            if cached_auth_type is None or cached_auth_type == FunctionURLAuthType.NONE:
                try:
                    lambda_client.remove_permission(
                        FunctionName=function_name,
                        StatementId="FunctionURLAllowPublicAccess",
                    )
                except lambda_client.exceptions.ResourceNotFoundException:
                    # Permission doesn't exist - either it was already removed,
                    # or the function was using AWS_IAM auth type
                    pass
        except lambda_client.exceptions.ResourceNotFoundException:
            self.logging.info(f"No Function URL found for {function_name}")
            return False
        else:
            # Only runs if no exception was raised - cleanup cache
            if function_name in self._function_urls:
                del self._function_urls[function_name]
            return True

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

    def cleanup_ecr_repository(
        self,
        boto3_session: boto3.session.Session,
        cache_client: Cache,
        dry_run: bool = False,
    ) -> List[str]:
        """Remove ECR repository used for container images.

        Args:
            boto3_session: boto3 session for AWS API calls
            cache_client: SeBS cache instance
            dry_run: when true, skip actual deletion

        Returns:
            list of deleted ECR repositories (currently always one)
        """
        deleted: List[str] = []
        dry_run_tag = "[DRY-RUN] " if dry_run else ""
        repo_name = self._container_repository

        if repo_name is None:
            return deleted

        try:
            ecr_client = boto3_session.client("ecr", region_name=cast(str, self._region))

            try:
                ecr_client.describe_repositories(repositoryNames=[repo_name])
                self.logging.info(f"{dry_run_tag}Deleting ECR repository: {repo_name}")
                deleted.append(repo_name)

                if dry_run:
                    return deleted

                ecr_client.delete_repository(repositoryName=repo_name, force=True)

            except ecr_client.exceptions.RepositoryNotFoundException:
                self.logging.warning(f"ECR repository {repo_name} does not exist")
            except Exception as e:
                self.logging.error(f"Failed to delete ECR repository {repo_name}: {e}")
            finally:
                cache_client.remove_config_key(["aws", "resources", "container_repository"])
                cache_client.remove_config_key(["aws", "resources", "docker"])

                self._docker_registry = None
                self._docker_username = None
                self._container_repository = None

        except Exception as e:
            self.logging.error(f"Failed to create ECR client: {e}")

        if not dry_run:
            cache_client.invalidate_all_container_uris("aws")

        return deleted

    def cleanup_cloudwatch_logs(
        self, function_names: List[str], boto3_session: boto3.session.Session, dry_run: bool
    ) -> List[str]:
        """Remove CloudWatch logs for selected functions.

        Args:
            function_names: list of function names to clean up logs for
            boto3_session: boto3 session for AWS API calls
            dry_run: when true, skip actual deletion

        Returns:
            list of deleted log group names
        """

        deleted: List[str] = []
        dry_run_tag = "[DRY-RUN] " if dry_run else ""
        if not function_names:
            return deleted

        logs_client = boto3_session.client("logs", region_name=self._region)

        for func_name in function_names:
            log_group = f"/aws/lambda/{func_name}"
            try:
                response = logs_client.describe_log_groups(logGroupNamePrefix=log_group)

                for group in response.get("logGroups", []):
                    group_name = group["logGroupName"]
                    if group_name != log_group:
                        continue

                    self.logging.info(f"{dry_run_tag}Deleting log group: {group_name}")
                    deleted.append(group_name)
                    if dry_run:
                        continue

                    try:
                        logs_client.delete_log_group(logGroupName=group_name)
                    except Exception as e:
                        self.logging.error(f"Failed to delete log group {group_name}: {e}")

            except Exception as e:
                self.logging.error(f"Failed to describe log groups for {func_name}: {e}")

        return deleted

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

        if "function-urls" in dct:
            for key, value in dct["function-urls"].items():
                ret._function_urls[key] = AWSResources.FunctionURL.deserialize(value)

        ret._use_function_url = dct.get("use-function-url", False)
        auth_type_str = dct.get("function-url-auth-type", "NONE")
        ret.function_url_auth_type = FunctionURLAuthType.from_string(auth_type_str)

    def serialize(self) -> dict:
        """Serialize AWS resources to dictionary.

        Returns:
            dict: Serialized resource configuration
        """
        out = {
            **super().serialize(),
            "lambda-role": self._lambda_role,
            "http-apis": {key: value.serialize() for (key, value) in self._http_apis.items()},
            "function-urls": {
                key: value.serialize() for (key, value) in self._function_urls.items()
            },
            "use-function-url": self._use_function_url,
            "function-url-auth-type": self._function_url_auth_type.value,
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
        for name, func_url in self._function_urls.items():
            cache.update_config(
                val=func_url.serialize(), keys=["aws", "resources", "function-urls", name]
            )
        cache.update_config(
            val=self._use_function_url, keys=["aws", "resources", "use-function-url"]
        )
        cache.update_config(
            val=self._function_url_auth_type.value,
            keys=["aws", "resources", "function-url-auth-type"],
        )

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

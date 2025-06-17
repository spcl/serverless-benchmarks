import math
import os
import shutil
import time
import uuid
from typing import cast, Dict, List, Optional, Tuple, Type, Union  # noqa

import boto3
import docker

from sebs.aws.dynamodb import DynamoDB
from sebs.aws.resources import AWSSystemResources
from sebs.aws.s3 import S3
from sebs.aws.function import LambdaFunction
from sebs.aws.container import ECRContainer
from sebs.aws.config import AWSConfig
from sebs.faas.config import Resources
from sebs.utils import execute
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers
from sebs.faas.function import Function, ExecutionResult, Trigger, FunctionConfig
from sebs.faas.system import System


class AWS(System):
    logs_client = None
    cached = False
    _config: AWSConfig

    @staticmethod
    def name():
        return "aws"

    @staticmethod
    def typename():
        return "AWS"

    @staticmethod
    def function_type() -> "Type[Function]":
        return LambdaFunction

    @property
    def config(self) -> AWSConfig:
        return self._config

    @property
    def system_resources(self) -> AWSSystemResources:
        return cast(AWSSystemResources, self._system_resources)

    """
        :param cache_client: Function cache instance
        :param config: Experiments config
        :param docker_client: Docker instance
    """

    def __init__(
        self,
        sebs_config: SeBSConfig,
        config: AWSConfig,
        cache_client: Cache,
        docker_client: docker.client,
        logger_handlers: LoggingHandlers,
    ):
        super().__init__(
            sebs_config,
            cache_client,
            docker_client,
            AWSSystemResources(config, cache_client, docker_client, logger_handlers),
        )
        self.logging_handlers = logger_handlers
        self._config = config
        self.storage: Optional[S3] = None
        self.nosql_storage: Optional[DynamoDB] = None

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        # thread-safe
        self.session = boto3.session.Session(
            aws_access_key_id=self.config.credentials.access_key,
            aws_secret_access_key=self.config.credentials.secret_key,
        )
        self.get_lambda_client()
        self.system_resources.initialize_session(self.session)
        self.initialize_resources(select_prefix=resource_prefix)

        self.ecr_client = ECRContainer(
            self.system_config, self.session, self.config, self.docker_client
        )

    def get_lambda_client(self):
        if not hasattr(self, "client"):
            self.client = self.session.client(
                service_name="lambda",
                region_name=self.config.region,
            )
        return self.client

    """
        It would be sufficient to just pack the code and ship it as zip to AWS.
        However, to have a compatible function implementation across providers,
        we create a small module.
        Issue: relative imports in Python when using storage wrapper.
        Azure expects a relative import inside a module thus it's easier
        to always create a module.

        Structure:
        function
        - function.py
        - storage.py
        - resources
        handler.py

        benchmark: benchmark name
    """

    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int, str]:

        container_uri = ""

        # if the containerized deployment is set to True
        if container_deployment:
            # build base image and upload to ECR
            _, container_uri = self.ecr_client.build_base_image(
                directory, language_name, language_version, architecture, benchmark, is_cached
            )

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        # move all files to 'function' except handler.py
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)
        # FIXME: use zipfile
        # create zip with hidden directory but without parent directory
        execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True, cwd=directory)
        benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark))
        self.logging.info("Created {} archive".format(benchmark_archive))

        bytes_size = os.path.getsize(os.path.join(directory, benchmark_archive))
        mbytes = bytes_size / 1024.0 / 1024.0
        self.logging.info("Zip archive size {:2f} MB".format(mbytes))

        return (
            os.path.join(directory, "{}.zip".format(benchmark)),
            bytes_size,
            container_uri,
        )

    def _map_architecture(self, architecture: str) -> str:

        if architecture == "x64":
            return "x86_64"
        return architecture

    def _map_language_runtime(self, language: str, runtime: str):

        # AWS uses different naming scheme for Node.js versions
        # For example, it's 12.x instead of 12.
        if language == "nodejs":
            return f"{runtime}.x"
        return runtime

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str,
    ) -> "LambdaFunction":

        package = code_package.code_location
        benchmark = code_package.benchmark
        language = code_package.language_name
        language_runtime = code_package.language_version
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory
        code_size = code_package.code_size
        code_bucket: Optional[str] = None
        func_name = AWS.format_function_name(func_name)
        function_cfg = FunctionConfig.from_benchmark(code_package)
        architecture = function_cfg.architecture.value
        # we can either check for exception or use list_functions
        # there's no API for test
        try:
            ret = self.client.get_function(FunctionName=func_name)
            self.logging.info(
                "Function {} exists on AWS, retrieve configuration.".format(func_name)
            )
            # Here we assume a single Lambda role
            lambda_function = LambdaFunction(
                func_name,
                code_package.benchmark,
                ret["Configuration"]["FunctionArn"],
                code_package.hash,
                language_runtime,
                self.config.resources.lambda_role(self.session),
                function_cfg,
            )
            self.update_function(lambda_function, code_package, container_deployment, container_uri)
            lambda_function.updated_code = True
            # TODO: get configuration of REST API
        except self.client.exceptions.ResourceNotFoundException:
            self.logging.info("Creating function {} from {}".format(func_name, package))

            create_function_params = {
                "FunctionName": func_name,
                "Role": self.config.resources.lambda_role(self.session),
                "MemorySize": memory,
                "Timeout": timeout,
                "Architectures": [self._map_architecture(architecture)],
                "Code": {},
            }

            if container_deployment:
                create_function_params["PackageType"] = "Image"
                create_function_params["Code"] = {"ImageUri": container_uri}
            else:
                create_function_params["PackageType"] = "Zip"
                if code_size < 50 * 1024 * 1024:
                    package_body = open(package, "rb").read()
                    create_function_params["Code"] = {"ZipFile": package_body}
                else:
                    code_package_name = cast(str, os.path.basename(package))

                    storage_client = self.system_resources.get_storage()
                    code_bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
                    code_prefix = os.path.join(benchmark, code_package_name)
                    storage_client.upload(code_bucket, package, code_prefix)

                    self.logging.info(
                        "Uploading function {} code to {}".format(func_name, code_bucket)
                    )
                    create_function_params["Code"] = {
                        "S3Bucket": code_bucket,
                        "S3Key": code_prefix,
                    }

                create_function_params["Runtime"] = "{}{}".format(
                    language, self._map_language_runtime(language, language_runtime)
                )
                create_function_params["Handler"] = "handler.handler"

            create_function_params = {
                k: v for k, v in create_function_params.items() if v is not None
            }
            ret = self.client.create_function(**create_function_params)

            lambda_function = LambdaFunction(
                func_name,
                code_package.benchmark,
                ret["FunctionArn"],
                code_package.hash,
                language_runtime,
                self.config.resources.lambda_role(self.session),
                function_cfg,
                code_bucket,
            )

            self.wait_function_active(lambda_function)

            # Update environment variables
            self.update_function_configuration(lambda_function, code_package)

        # Add LibraryTrigger to a new function
        from sebs.aws.triggers import LibraryTrigger

        trigger = LibraryTrigger(func_name, self)
        trigger.logging_handlers = self.logging_handlers
        lambda_function.add_trigger(trigger)

        return lambda_function

    def cached_function(self, function: Function):

        from sebs.aws.triggers import LibraryTrigger

        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            trigger.logging_handlers = self.logging_handlers
            cast(LibraryTrigger, trigger).deployment_client = self
        for trigger in function.triggers(Trigger.TriggerType.HTTP):
            trigger.logging_handlers = self.logging_handlers

    """
        Update function code and configuration on AWS.

        :param benchmark: benchmark name
        :param name: function name
        :param code_package: path to code package
        :param code_size: size of code package in bytes
        :param timeout: function timeout in seconds
        :param memory: memory limit for function
    """

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str,
    ):
        name = function.name
        function = cast(LambdaFunction, function)

        if container_deployment:
            self.client.update_function_code(FunctionName=name, ImageUri=container_uri)
        else:
            code_size = code_package.code_size
            package = code_package.code_location
            benchmark = code_package.benchmark

            function_cfg = FunctionConfig.from_benchmark(code_package)
            architecture = function_cfg.architecture.value

            # Run AWS update
            # AWS Lambda limit on zip deployment
            if code_size < 50 * 1024 * 1024:
                with open(package, "rb") as code_body:
                    self.client.update_function_code(
                        FunctionName=name,
                        ZipFile=code_body.read(),
                        Architectures=[self._map_architecture(architecture)],
                    )
            # Upload code package to S3, then update
            else:
                code_package_name = os.path.basename(package)

                storage = self.system_resources.get_storage()
                bucket = function.code_bucket(code_package.benchmark, cast(S3, storage))
                code_prefix = os.path.join(benchmark, architecture, code_package_name)
                storage.upload(bucket, package, code_prefix)

                self.client.update_function_code(
                    FunctionName=name,
                    S3Bucket=bucket,
                    S3Key=code_prefix,
                    Architectures=[self._map_architecture(architecture)],
                )

        self.wait_function_updated(function)
        self.logging.info(f"Updated code of {name} function. ")
        # and update config
        self.update_function_configuration(function, code_package)

    def update_function_configuration(
        self, function: Function, code_package: Benchmark, env_variables: dict = {}
    ):

        # We can only update storage configuration once it has been processed for this benchmark
        assert code_package.has_input_processed

        envs = env_variables.copy()
        if code_package.uses_nosql:

            nosql_storage = self.system_resources.get_nosql_storage()
            for original_name, actual_name in nosql_storage.get_tables(
                code_package.benchmark
            ).items():
                envs[f"NOSQL_STORAGE_TABLE_{original_name}"] = actual_name

        # AWS Lambda will overwrite existing variables
        # If we modify them, we need to first read existing ones and append.
        if len(envs) > 0:

            response = self.client.get_function_configuration(FunctionName=function.name)
            # preserve old variables while adding new ones.
            # but for conflict, we select the new one
            if "Environment" in response:
                envs = {**response["Environment"]["Variables"], **envs}

        function = cast(LambdaFunction, function)
        # We only update envs if anything new was added
        if len(envs) > 0:
            self.client.update_function_configuration(
                FunctionName=function.name,
                Timeout=function.config.timeout,
                MemorySize=function.config.memory,
                Environment={"Variables": envs},
            )
        else:
            self.client.update_function_configuration(
                FunctionName=function.name,
                Timeout=function.config.timeout,
                MemorySize=function.config.memory,
            )
        self.wait_function_updated(function)
        self.logging.info(f"Updated configuration of {function.name} function. ")

    # @staticmethod
    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        # Create function name
        resource_id = resources.resources_id if resources else self.config.resources.resources_id
        func_name = "sebs-{}-{}-{}-{}-{}".format(
            resource_id,
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
            code_package.architecture,
        )
        if code_package.container_deployment:
            func_name = f"{func_name}-docker"
        return AWS.format_function_name(func_name)

    @staticmethod
    def format_function_name(func_name: str) -> str:
        # AWS Lambda does not allow hyphens in function names
        func_name = func_name.replace("-", "_")
        func_name = func_name.replace(".", "_")
        return func_name

    """
        FIXME: does not clean the cache
    """

    def delete_function(self, func_name: Optional[str]):
        self.logging.debug("Deleting function {}".format(func_name))
        try:
            self.client.delete_function(FunctionName=func_name)
        except Exception:
            self.logging.debug("Function {} does not exist!".format(func_name))

    """
        Prepare AWS resources to store experiment results.
        Allocate one bucket.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    """

    # def prepare_experiment(self, benchmark: str):
    #    logs_bucket = self.get_storage().add_output_bucket(benchmark, suffix="logs")
    #    return logs_bucket

    """
        Accepts AWS report after function invocation.
        Returns a dictionary filled with values with various metrics such as
        time, invocation time and memory consumed.

        :param log: decoded log from CloudWatch or from synchronuous invocation
        :return: dictionary with parsed values
    """

    @staticmethod
    def parse_aws_report(
        log: str, requests: Union[ExecutionResult, Dict[str, ExecutionResult]]
    ) -> str:
        aws_vals = {}
        for line in log.split("\t"):
            if not line.isspace():
                split = line.split(":")
                aws_vals[split[0]] = split[1].split()[0]
        if "START RequestId" in aws_vals:
            request_id = aws_vals["START RequestId"]
        else:
            request_id = aws_vals["REPORT RequestId"]
        if isinstance(requests, ExecutionResult):
            output = cast(ExecutionResult, requests)
        else:
            if request_id not in requests:
                return request_id
            output = requests[request_id]
        output.request_id = request_id
        output.provider_times.execution = int(float(aws_vals["Duration"]) * 1000)
        output.stats.memory_used = float(aws_vals["Max Memory Used"])
        if "Init Duration" in aws_vals:
            output.provider_times.initialization = int(float(aws_vals["Init Duration"]) * 1000)
        output.billing.billed_time = int(aws_vals["Billed Duration"])
        output.billing.memory = int(aws_vals["Memory Size"])
        output.billing.gb_seconds = output.billing.billed_time * output.billing.memory
        return request_id

    def shutdown(self) -> None:
        super().shutdown()

    def get_invocation_error(self, function_name: str, start_time: int, end_time: int):
        if not self.logs_client:
            self.logs_client = boto3.client(
                service_name="logs",
                aws_access_key_id=self.config.credentials.access_key,
                aws_secret_access_key=self.config.credentials.secret_key,
                region_name=self.config.region,
            )

        response = None
        while True:
            query = self.logs_client.start_query(
                logGroupName="/aws/lambda/{}".format(function_name),
                # queryString="filter @message like /REPORT/",
                queryString="fields @message",
                startTime=start_time,
                endTime=end_time,
            )
            query_id = query["queryId"]

            while response is None or response["status"] == "Running":
                self.logging.info("Waiting for AWS query to complete ...")
                time.sleep(5)
                response = self.logs_client.get_query_results(queryId=query_id)
            if len(response["results"]) == 0:
                self.logging.info("AWS logs are not yet available, repeat after 15s...")
                time.sleep(15)
                response = None
            else:
                break
        self.logging.error(f"Invocation error for AWS Lambda function {function_name}")
        for message in response["results"]:
            for value in message:
                if value["field"] == "@message":
                    self.logging.error(value["value"])

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):

        if not self.logs_client:
            self.logs_client = boto3.client(
                service_name="logs",
                aws_access_key_id=self.config.credentials.access_key,
                aws_secret_access_key=self.config.credentials.secret_key,
                region_name=self.config.region,
            )

        query = self.logs_client.start_query(
            logGroupName="/aws/lambda/{}".format(function_name),
            queryString="filter @message like /REPORT/",
            startTime=math.floor(start_time),
            endTime=math.ceil(end_time + 1),
            limit=10000,
        )
        query_id = query["queryId"]
        response = None

        while response is None or response["status"] == "Running":
            self.logging.info("Waiting for AWS query to complete ...")
            time.sleep(1)
            response = self.logs_client.get_query_results(queryId=query_id)
        # results contain a list of matches
        # each match has multiple parts, we look at `@message` since this one
        # contains the report of invocation
        results = response["results"]
        results_count = len(requests.keys())
        results_processed = 0
        requests_ids = set(requests.keys())
        for val in results:
            for result_part in val:
                if result_part["field"] == "@message":
                    request_id = AWS.parse_aws_report(result_part["value"], requests)
                    if request_id in requests:
                        results_processed += 1
                        requests_ids.remove(request_id)
        self.logging.info(
            f"Received {len(results)} entries, found results for {results_processed} "
            f"out of {results_count} invocations"
        )

    def create_trigger(self, func: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        from sebs.aws.triggers import HTTPTrigger

        function = cast(LambdaFunction, func)

        if trigger_type == Trigger.TriggerType.HTTP:

            api_name = "{}-http-api".format(function.name)
            http_api = self.config.resources.http_api(api_name, function, self.session)
            # https://aws.amazon.com/blogs/compute/announcing-http-apis-for-amazon-api-gateway/
            # but this is wrong - source arn must be {api-arn}/*/*
            self.get_lambda_client().add_permission(
                FunctionName=function.name,
                StatementId=str(uuid.uuid1()),
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"{http_api.arn}/*/*",
            )
            trigger = HTTPTrigger(http_api.endpoint, api_name)
            self.logging.info(
                f"Created HTTP trigger for {func.name} function. "
                "Sleep 5 seconds to avoid cloud errors."
            )
            time.sleep(5)
            trigger.logging_handlers = self.logging_handlers
        elif trigger_type == Trigger.TriggerType.LIBRARY:
            # should already exist
            return func.triggers(Trigger.TriggerType.LIBRARY)[0]
        else:
            raise RuntimeError("Not supported!")

        function.add_trigger(trigger)
        self.cache_client.update_function(function)
        return trigger

    def _enforce_cold_start(self, function: Function, code_package: Benchmark):
        func = cast(LambdaFunction, function)
        self.update_function_configuration(
            func, code_package, {"ForceColdStart": str(self.cold_start_counter)}
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func, code_package)
        self.logging.info("Sent function updates enforcing cold starts.")
        for func in functions:
            lambda_function = cast(LambdaFunction, func)
            self.wait_function_updated(lambda_function)
        self.logging.info("Finished function updates enforcing cold starts.")

    def wait_function_active(self, func: LambdaFunction):

        self.logging.info("Waiting for Lambda function to be created...")
        waiter = self.client.get_waiter("function_active_v2")
        waiter.wait(FunctionName=func.name)
        self.logging.info("Lambda function has been created.")

    def wait_function_updated(self, func: LambdaFunction):

        self.logging.info("Waiting for Lambda function to be updated...")
        waiter = self.client.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=func.name)
        self.logging.info("Lambda function has been updated.")

    def disable_rich_output(self):
        self.ecr_client.disable_rich_output = True

    def get_invocation_logs(self, function_name: str, invocation_id: str) -> List[str]:
        if not self.logs_client:
            self.logs_client = boto3.client(
                service_name="logs",
                aws_access_key_id=self.config.credentials.access_key,
                aws_secret_access_key=self.config.credentials.secret_key,
                region_name=self.config.region,
            )

        log_group_name = f"/aws/lambda/{function_name}"
        end_time = int(time.time() * 1000)
        start_time = end_time - (24 * 60 * 60 * 1000)  # 24 hours ago

        messages: List[str] = []
        try:
            paginator = self.logs_client.get_paginator("filter_log_events")
            response_iterator = paginator.paginate(
                logGroupName=log_group_name,
                startTime=start_time,
                endTime=end_time,
                filterPattern=invocation_id,
                # limit=10000 # Default is 1MB or 10k events, should be enough for single invocation
            )

            for page in response_iterator:
                for event in page.get("events", []):
                    messages.append(event["message"])
                # If we found events, and they all should contain the invocation_id,
                # we can assume these are all the logs for this specific invocation.
                # However, AWS Lambda might split one invocation's logs across multiple streams
                # or even push them with slight delays.
                # For simplicity, if we get any results, we might assume these are sufficient.
                # If not, we might need a more sophisticated check or rely on the fact
                # that filterPattern should be quite specific for an invocation ID.

        except self.logs_client.exceptions.ResourceNotFoundException:
            self.logging.warning(
                f"Log group {log_group_name} not found for function {function_name}."
            )
            return []
        except Exception as e:
            self.logging.error(
                f"Error retrieving logs for {function_name}, invocation {invocation_id}: {e}"
            )
            return []

        return messages

import math
import os
import shutil
import time
import uuid
from typing import cast, Dict, List, Optional, Tuple, Type, Union  # noqa

import boto3
import docker
import base64
from botocore.exceptions import ClientError

from sebs.aws.s3 import S3
from sebs.aws.function import LambdaFunction
from sebs.aws.config import AWSConfig
from sebs.faas.config import Resources
from sebs.utils import execute
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.utils import LoggingHandlers, DOCKER_DIR
from sebs.faas.function import Function, ExecutionResult, Trigger, FunctionConfig
from sebs.faas.storage import PersistentStorage
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
        super().__init__(sebs_config, cache_client, docker_client)
        self.logging_handlers = logger_handlers
        self._config = config
        self.storage: Optional[S3] = None

    def initialize(self, config: Dict[str, str] = {}, resource_prefix: Optional[str] = None):
        # thread-safe
        self.session = boto3.session.Session(
            aws_access_key_id=self.config.credentials.access_key,
            aws_secret_access_key=self.config.credentials.secret_key,
        )
        self.get_lambda_client()
        self.get_storage()
        self.initialize_resources(select_prefix=resource_prefix)

    def get_lambda_client(self):
        if not hasattr(self, "client"):
            self.client = self.session.client(
                service_name="lambda",
                region_name=self.config.region,
            )
        return self.client

    """
        Create a client instance for cloud storage. When benchmark and buckets
        parameters are passed, then storage is initialized with required number
        of buckets. Buckets may be created or retrieved from cache.

        :param benchmark: benchmark name
        :param buckets: tuple of required input/output buckets
        :param replace_existing: replace existing files in cached buckets?
        :return: storage client
    """

    def get_storage(self, replace_existing: bool = False) -> PersistentStorage:
        if not self.storage:
            self.storage = S3(
                self.session,
                self.cache_client,
                self.config.resources,
                self.config.region,
                access_key=self.config.credentials.access_key,
                secret_key=self.config.credentials.secret_key,
                replace_existing=replace_existing,
            )
            self.storage.logging_handlers = self.logging_handlers
        else:
            self.storage.replace_existing = replace_existing
        return self.storage

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
        benchmark: str,
        is_cached: bool,
        container_deployment: bool,
    ) -> Tuple[str, int]:

        print("The containerzied deployment is", container_deployment)
        print("PK: the directory is", directory)

        # if the containerzied deployment is set to True
        if container_deployment:
            # build base image and upload to ECR 
            print("Now buildin the base Iamge")
            print("the directory is", directory)
            self.build_base_image(directory, language_name, language_version, benchmark, is_cached)

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir) 
        print("the function dir is", function_dir)
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

        return os.path.join(directory, "{}.zip".format(benchmark)), bytes_size

    def _map_architecture(self, architecture: str) -> str:

        if architecture == "x64":
            return "x86_64"
        return architecture

    def build_base_image(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> bool:
        """
        When building function for the first time (according to SeBS cache),
        check if Docker image is available in the registry.
        If yes, then skip building.
        If no, then continue building.

        For every subsequent build, we rebuild image and push it to the
        registry. These are triggered by users modifying code and enforcing
        a build.
        """
        # get registry name 
        print("PK: Printing self config to see the resource", self.config)
        print("PK: The region is", self.config.region)
        print("PK: Printing self config to see the resource", dir(self.config))
        print("PK: Printing self config to see the resource", self.config.credentials.account_id)
        print("PK: DIR Printing self config to see the resource", dir(self.config))
        print("PK: TRhe directory is", directory)

        account_id = self.config.credentials.account_id
        region = self.config.region
        registry_name = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
        repository_name = "test_repo"
        image_tag = self.system_config.benchmark_image_tag(
            self.name(), benchmark, language_name, language_version
        )
        repository_uri = f"{registry_name}/{repository_name}:{image_tag}"


        print("PK: The Image tagg is", image_tag)
        print("The region is", region)
        ecr_client = boto3.client('ecr', region_name=region)

        def image_exists_in_ecr(repository_uri):
            repository_name, image_tag = repository_uri.split(':')[-2], repository_uri.split(':')[-1]
            try:
                response = ecr_client.describe_images(
                    repositoryName=repository_name,
                    imageIds=[{'imageTag': image_tag}]
                )
                if response['imageDetails']:
                    return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'ImageNotFoundException':
                    return False
                else:
                    raise e
        # PK: Needs to be refactored
        def repository_exists(repository_name):
            try:
                ecr_client.describe_repositories(repositoryNames=[repository_name])
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                    return False
                else:
                    self.logging.error(f"Error checking repository: {e}")
                    raise e 

        # PK: Needs to be refactored
        def create_ecr_repository(repository_name):
            if not repository_exists(repository_name):
                try:
                    ecr_client.create_repository(repositoryName=repository_name)
                    self.logging.info(f"Created ECR repository: {repository_name}")
                except ClientError as e:
                    if e.response['Error']['Code'] != 'RepositoryAlreadyExistsException':
                        self.logging.error(f"Failed to create ECR repository: {e}")
                        raise e

        # Create repository if it does not exist
        create_ecr_repository(repository_name)

        # PK: To Do: Check if we the image is already in the registry. For AWS we need to check in the ECR.
        # cached package, rebuild not enforced -> check for new one
        print("Is chacned ornot", is_cached)
        if is_cached:
            if image_exists_in_ecr(repository_uri):
                self.logging.info(
                    f"Skipping building OpenWhisk Docker package for {benchmark}, using "
                    f"Docker image {repository_name}:{image_tag} from registry: "
                    f"{registry_name}."
                )
                return False
            else:
                # image doesn't exist, let's continue
                self.logging.info(
                    f"Image {repository_name}:{image_tag} doesn't exist in the registry, "
                    f"building the image for {benchmark}."
                )

        build_dir = os.path.join(directory, "docker")
        print("the build dir is", build_dir)
        os.makedirs(build_dir, exist_ok=True)
        print("Copying the file from", os.path.join(DOCKER_DIR, self.name(), language_name, "Dockerfile.function"))

        shutil.copy(
            os.path.join(DOCKER_DIR, self.name(), language_name, "Dockerfile.function"),
            os.path.join(build_dir, "Dockerfile"),
        )
        for fn in os.listdir(directory):
            if fn not in ("index.js", "__main__.py"):
                file = os.path.join(directory, fn)
                shutil.move(file, build_dir)

        with open(os.path.join(build_dir, ".dockerignore"), "w") as f:
            f.write("Dockerfile")

        builder_image = self.system_config.benchmark_base_images(self.name(), language_name)[
            language_version
        ]
        print("THe builder Image is", builder_image)
        self.logging.info(f"Build the benchmark base image {repository_name}:{image_tag}.")

        buildargs = {"VERSION": language_version, "BASE_IMAGE": builder_image}
        print("the Build args are", buildargs)
        image, _ = self.docker_client.images.build(
            tag=repository_uri, path=build_dir, buildargs=buildargs
        )
        print(f"The etag for the build is {repository_name}:{image_tag}")
        print("The Image After building is", image) 

        # Now push the image to the registry
        # image will be located in a private repository // for AWS Image should be in the ECR
        self.logging.info(
            f"Push the benchmark base image {repository_name}:{image_tag} "
            f"to registry: {registry_name}."
        )

        def push_image_to_ecr():
            auth = ecr_client.get_authorization_token()
            auth_data = auth['authorizationData'][0]
            token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
            username, password = token.split(':')
            registry_url = auth_data['proxyEndpoint']

            self.docker_client.login(username=username, password=password, registry=registry_url)
            ret = self.docker_client.images.push(
                repository=repository_uri, tag=image_tag, stream=True, decode=True
            )
            for val in ret:
                if "error" in val:
                    self.logging.error(f"Failed to push the image to registry {registry_name}")
                    raise RuntimeError(val)

        try:
            push_image_to_ecr()
        except RuntimeError as e:
            if 'authorization token has expired' in str(e):
                self.logging.info("Authorization token expired. Re-authenticating and retrying...")
                push_image_to_ecr()
            else:
                raise e

        return True

    def _map_language_runtime(self, language: str, runtime: str):

        # AWS uses different naming scheme for Node.js versions
        # For example, it's 12.x instead of 12.
        if language == "nodejs":
            return f"{runtime}.x"
        return runtime

    def create_function(self, code_package: Benchmark, func_name: str) -> "LambdaFunction":

        package = code_package.code_location
        benchmark = code_package.benchmark
        language = code_package.language_name
        language_runtime = code_package.language_version
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory
        code_size = code_package.code_size
        code_bucket: Optional[str] = None
        func_name = AWS.format_function_name(func_name)
        storage_client = self.get_storage()
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
            self.update_function(lambda_function, code_package)
            lambda_function.updated_code = True
            # TODO: get configuration of REST API
        except self.client.exceptions.ResourceNotFoundException:
            self.logging.info("Creating function {} from {}".format(func_name, package))

            # AWS Lambda limit on zip deployment size
            # Limit to 50 MB
            # mypy doesn't recognize correctly the case when the same
            # variable has different types across the path
            code_config: Dict[str, Union[str, bytes]]
            if code_size < 50 * 1024 * 1024:
                package_body = open(package, "rb").read()
                code_config = {"ZipFile": package_body}
            # Upload code package to S3, then use it
            else:
                code_package_name = cast(str, os.path.basename(package))

                code_bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
                code_prefix = os.path.join(benchmark, architecture, code_package_name)
                storage_client.upload(code_bucket, package, code_prefix)

                self.logging.info("Uploading function {} code to {}".format(func_name, code_bucket))
                code_config = {"S3Bucket": code_bucket, "S3Key": code_prefix}
            ret = self.client.create_function(
                FunctionName=func_name,
                Runtime="{}{}".format(
                    language, self._map_language_runtime(language, language_runtime)
                ),
                Handler="handler.handler",
                Role=self.config.resources.lambda_role(self.session),
                MemorySize=memory,
                Timeout=timeout,
                Code=code_config,
                Architectures=[self._map_architecture(architecture)],
            )

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

    def update_function(self, function: Function, code_package: Benchmark):

        function = cast(LambdaFunction, function)
        name = function.name
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

            storage = cast(S3, self.get_storage())
            bucket = function.code_bucket(code_package.benchmark, storage)
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
        self.client.update_function_configuration(
            FunctionName=name,
            Timeout=function.config.timeout,
            MemorySize=function.config.memory,
        )
        self.wait_function_updated(function)
        self.logging.info(f"Updated configuration of {name} function. ")
        self.wait_function_updated(function)
        self.logging.info("Published new function code")

    def update_function_configuration(self, function: Function, benchmark: Benchmark):
        function = cast(LambdaFunction, function)
        self.client.update_function_configuration(
            FunctionName=function.name,
            Timeout=function.config.timeout,
            MemorySize=function.config.memory,
        )
        self.wait_function_updated(function)
        self.logging.info(f"Updated configuration of {function.name} function. ")

    @staticmethod
    def default_function_name(code_package: Benchmark) -> str:
        # Create function name
        func_name = "{}-{}-{}-{}".format(
            code_package.benchmark,
            code_package.language_name,
            code_package.language_version,
            code_package.architecture,
        )
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

    def _enforce_cold_start(self, function: Function):
        func = cast(LambdaFunction, function)
        self.get_lambda_client().update_function_configuration(
            FunctionName=func.name,
            Timeout=func.config.timeout,
            MemorySize=func.config.memory,
            Environment={"Variables": {"ForceColdStart": str(self.cold_start_counter)}},
        )

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
        self.cold_start_counter += 1
        for func in functions:
            self._enforce_cold_start(func)
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

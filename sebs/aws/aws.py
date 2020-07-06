import base64
import datetime
import json
import logging
import os
import shutil
import time
import uuid
from typing import Dict, List, Optional, Tuple, Union, cast

import boto3
import docker

from sebs.aws.s3 import S3
from sebs.aws.config import AWSConfig
from sebs import utils
from sebs.benchmark import Benchmark
from sebs.cache import Cache
from sebs.config import SeBSConfig
from ..faas.function import Function, ExecutionResult
from ..faas.storage import PersistentStorage
from ..faas.system import System


class classproperty(property):
    def __get__(self, cls, owner):
        return classmethod(self.fget).__get__(None, owner)()


class AWS(System):
    logs_client = None
    storage: S3
    cached = False
    _config: AWSConfig

    # @classproperty
    @staticmethod
    def name():
        return "aws"

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
    ):
        super().__init__(sebs_config, cache_client, docker_client)
        self._config = config

    def initialize(self, config: Dict[str, str] = {}):
        self.get_lambda_client()
        self.get_storage()

    def get_lambda_client(self):
        if not hasattr(self, "client"):
            self.client = boto3.client(
                service_name="lambda",
                aws_access_key_id=self.config.credentials.access_key,
                aws_secret_access_key=self.config.credentials.secret_key,
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
        if not hasattr(self, "storage"):
            self.storage = S3(
                self.cache_client,
                self.config.region,
                access_key=self.config.credentials.access_key,
                secret_key=self.config.credentials.secret_key,
                replace_existing=replace_existing,
            )
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

    def package_code(self, benchmark: Benchmark) -> Tuple[str, int]:

        directory = benchmark.build()

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        directory = benchmark.code_location
        package_config = CONFIG_FILES[benchmark.language_name]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        # move all files to 'function' except handler.py
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        cur_dir = os.getcwd()
        os.chdir(directory)
        # create zip with hidden directory but without parent directory
        utils.execute("zip -qu -r9 {}.zip * .".format(benchmark.benchmark), shell=True)
        benchmark_archive = "{}.zip".format(
            os.path.join(directory, benchmark.benchmark)
        )
        logging.info("Created {} archive".format(benchmark_archive))

        bytes_size = os.path.getsize(benchmark_archive)
        mbytes = bytes_size / 1024.0 / 1024.0
        logging.info("Zip archive size {:2f} MB".format(mbytes))
        os.chdir(cur_dir)
        return os.path.join(directory, "{}.zip".format(benchmark.benchmark)), bytes_size

    def create_lambda_function(
        self,
        benchmark: Benchmark,
        function_name: str,
        api_id: str,
        parent_id: str,
        package: str,
        code_size: int,
        memory: int,
        timeout: int,
        experiment_config: dict,
    ):
        language = benchmark.language_name
        language_runtime = benchmark.language_version
        logging.info("Creating function {} from {}".format(function_name, package))

        # TODO: create Lambda role
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
            bucket, idx = self.storage.add_input_bucket(function_name)
            self.storage.upload(bucket, package, code_package_name)
            logging.info(
                "Uploading function {} code to {}".format(function_name, bucket)
            )
            code_config = {"S3Bucket": bucket, "S3Key": code_package_name}
        self.client.create_function(
            FunctionName=function_name,
            Runtime="{}{}".format(language, language_runtime),
            Handler="handler.handler",
            Role=self.config.resources.lambda_role,
            MemorySize=memory,
            Timeout=timeout,
            Code=code_config,
        )
        while True:
            try:
                logging.info(
                    "Creating HTTP Trigger for function {} from {}".format(
                        function_name, package
                    )
                )
                url = self.create_http_trigger(function_name, api_id, parent_id)
                logging.info(url)
            except Exception as e:
                logging.info("Exception")
                logging.info(e)
                import traceback

                traceback.print_exc()
                api_client = boto3.client(
                    service_name="apigateway",
                    aws_access_key_id=self.config.credentials.access_key,
                    aws_secret_access_key=self.config.credentials.secret_key,
                    region_name=self.config.region,
                )
                resp = api_client.get_resources(restApiId=api_id)["items"]
                for v in resp:
                    if "pathPart" in v:
                        path = v["pathPart"]
                        if path == function_name:
                            resource_id = v["id"]
                            logging.info(
                                "Remove resource with path {} from {}".format(
                                    function_name, api_id
                                )
                            )
                            api_client.delete_resource(
                                restApiId=api_id, resourceId=resource_id
                            )
                            break
                # throttling on AWS
                continue
            logging.info("Done")
            break
        logging.info(
            "Created HTTP Trigger for function {} from {}".format(
                function_name, package
            )
        )
        return url

    def get_function(self, code_package: Benchmark) -> Function:

        if (
            code_package.language_version
            not in self.system_config.supported_language_versions(
                self.name(), code_package.language_name
            )
        ):
            raise Exception(
                "Unsupported {language} version {version} in AWS!".format(
                    language=code_package.language_name,
                    version=code_package.language_version,
                )
            )

        benchmark = code_package.benchmark
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return LambdaFunction(func_name, code_location, self)
        elif code_package.is_cached:

            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Run AWS-specific part of building code.
            package, code_size = self.package_code(code_package)
            package_body = open(package, "rb").read()
            self.update_function(
                benchmark, func_name, package, code_size, timeout, memory
            )

            cached_cfg = code_package.cached_config
            cached_cfg["code_size"] = code_size
            cached_cfg["timeout"] = timeout
            cached_cfg["memory"] = memory
            cached_cfg["hash"] = code_package.hash
            self.cache_client.update_function(
                self.name(), benchmark, code_package.language_name, package, cached_cfg
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return LambdaFunction(func_name, package, self)
        # no cached instance, create package and upload code
        else:

            code_location = code_package.code_location
            language = code_package.language_name
            language_runtime = code_package.language_version
            timeout = code_package.benchmark_config.timeout
            memory = code_package.benchmark_config.memory

            # Create function name
            func_name = "{}-{}-{}".format(benchmark, language, memory)
            # AWS Lambda does not allow hyphens in function names
            func_name = func_name.replace("-", "_")
            func_name = func_name.replace(".", "_")

            # Run AWS-specific part of building code.
            package, code_size = self.package_code(code_package)

            # we can either check for exception or use list_functions
            # there's no API for test
            try:
                self.client.get_function(FunctionName=func_name)
                self.update_function(
                    benchmark, func_name, package, code_size, timeout, memory
                )
                # TODO: get configuration of REST API
                url = None
            except self.client.exceptions.ResourceNotFoundException:
                logging.info(
                    "Creating function {} from {}".format(func_name, code_location)
                )

                # TODO: create Lambda role
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
                    bucket, idx = self.storage.add_input_bucket(benchmark)
                    self.storage.upload(bucket, code_package_name, package)
                    logging.info(
                        "Uploading function {} code to {}".format(func_name, bucket)
                    )
                    code_config = {"S3Bucket": bucket, "S3Key": code_package_name}
                self.client.create_function(
                    FunctionName=func_name,
                    Runtime="{}{}".format(language, language_runtime),
                    Handler="handler.handler",
                    Role=self.config.resources.lambda_role,
                    MemorySize=memory,
                    Timeout=timeout,
                    Code=code_config,
                )
                url = self.create_http_trigger(func_name, None, None)

            self.cache_client.add_function(
                deployment=self.name(),
                benchmark=benchmark,
                language=language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": language_runtime,
                    "role": self.config.resources.lambda_role,
                    "memory": memory,
                    "timeout": timeout,
                    "hash": code_package.hash,
                    "url": url,
                },
                storage_config={
                    "buckets": {
                        "input": self.storage.input_buckets,
                        "output": self.storage.output_buckets,
                    }
                },
            )
            # FIXME: fix after dissociating code package and benchmark
            code_package.query_cache()
            return LambdaFunction(func_name, package, self)

    def create_http_trigger(
        self, func_name: str, api_id: Optional[str], parent_id: Optional[str]
    ):

        # https://github.com/boto/boto3/issues/572
        # assumed we have: function name, region

        api_client = boto3.client(
            service_name="apigateway",
            aws_access_key_id=self.config.credentials.access_key,
            aws_secret_access_key=self.config.credentials.secret_key,
            region_name=self.config.region,
        )

        # create REST API
        if api_id is None:
            api_name = func_name
            api = api_client.create_rest_api(name=api_name)
            api_id = api["id"]
        if parent_id is None:
            resources = api_client.get_resources(restApiId=api_id)
            for r in resources["items"]:
                if r["path"] == "/":
                    parent_id = r["id"]

        # create resource
        # TODO: check if resource exists
        resource_id = None
        resp = api_client.get_resources(restApiId=api_id)["items"]
        for v in resp:
            if "pathPart" in v:
                path = v["pathPart"]
                if path == func_name:
                    resource_id = v["id"]
                    break
        if not resource_id:
            logging.info(func_name)
            logging.info(parent_id)
            resource = api_client.create_resource(
                restApiId=api_id, parentId=cast(str, parent_id), pathPart=func_name
            )
            logging.info(resource)
            resource_id = resource["id"]
        logging.info(
            "AWS: using REST API {api_id} with parent ID {parent_id}"
            "using resource ID {resource_id}".format(
                api_id=api_id, parent_id=parent_id, resource_id=resource_id
            )
        )

        # create POST method
        api_client.put_method(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            authorizationType="NONE",
            apiKeyRequired=False,
        )

        lambda_version = self.client.meta.service_model.api_version
        # get account information
        sts_client = boto3.client(
            service_name="sts",
            aws_access_key_id=self.config.credentials.access_key,
            aws_secret_access_key=self.config.credentials.secret_key,
            region_name=self.config.region,
        )
        account_id = sts_client.get_caller_identity()["Account"]

        uri_data = {
            "aws-region": self.config.resources.lambda_role,
            "api-version": lambda_version,
            "aws-acct-id": account_id,
            "lambda-function-name": func_name,
        }

        uri = (
            "arn:aws:apigateway:{aws-region}:lambda:path/{api-version}/"
            "functions/arn:aws:lambda:{aws-region}:{aws-acct-id}:function"
            ":{lambda-function-name}/invocations"
        ).format(**uri_data)

        # create integration
        api_client.put_integration(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            type="AWS",
            integrationHttpMethod="POST",
            uri=uri,
        )

        api_client.put_integration_response(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            statusCode="200",
            selectionPattern=".*",
        )

        # create POST method response
        api_client.put_method_response(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="POST",
            statusCode="200",
        )

        uri_data["aws-api-id"] = api_id
        source_arn = (
            "arn:aws:execute-api:{aws-region}:{aws-acct-id}:{aws-api-id}/*/"
            "POST/{lambda-function-name}"
        ).format(**uri_data)

        self.client.add_permission(
            FunctionName=func_name,
            StatementId=uuid.uuid4().hex,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn,
        )

        # state 'your stage name' was already created via API Gateway GUI
        stage_name = "name"
        api_client.create_deployment(restApiId=api_id, stageName=stage_name)
        uri_data["api_id"] = api_id
        uri_data["stage_name"] = stage_name
        url = (
            "https://{api_id}.execute-api.{aws-region}.amazonaws.com/"
            "{stage_name}/{lambda-function-name}"
        )
        return url.format(**uri_data)

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
        benchmark: str,
        name: str,
        code_package: str,
        code_size: int,
        timeout: int,
        memory: int,
    ):
        # AWS Lambda limit on zip deployment
        if code_size < 50 * 1024 * 1024:
            with open(code_package, "rb") as code_body:
                self.client.update_function_code(
                    FunctionName=name, ZipFile=code_body.read()
                )
        # Upload code package to S3, then update
        else:
            code_package_name = os.path.basename(code_package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package, code_package_name)
            self.client.update_function_code(
                FunctionName=name, S3Bucket=bucket, S3Key=code_package_name
            )
        # and update config
        self.client.update_function_configuration(
            FunctionName=name, Timeout=timeout, MemorySize=memory
        )
        logging.info(
            "Updating AWS code of function {} from {}".format(name, code_package)
        )

    """
        Prepare AWS resources to store experiment results.
        Allocate one bucket.

        :param benchmark: benchmark name
        :return: name of bucket to store experiment results
    """

    def prepare_experiment(self, benchmark: str):
        logs_bucket = self.storage.add_output_bucket(benchmark, suffix="logs")
        return logs_bucket

    """
        Accepts AWS report after function invocation.
        Returns a dictionary filled with values with various metrics such as
        time, invocation time and memory consumed.

        :param log: decoded log from CloudWatch or from synchronuous invocation
        :return: dictionary with parsed values
    """

    @staticmethod
    def parse_aws_report(log: str, output: ExecutionResult):
        aws_vals = {}
        for line in log.split("\t"):
            if not line.isspace():
                split = line.split(":")
                aws_vals[split[0]] = split[1].split()[0]
        output.request_id = aws_vals["START RequestId"]
        output.times.provider = int(float(aws_vals["Duration"]) * 1000)
        output.stats.memory_used = float(aws_vals["Max Memory Used"])
        if "Init Duration" in aws_vals:
            output.stats.init_time_reported = int(
                float(aws_vals["Init Duration"]) * 1000
            )
        output.billing.billed_time = int(aws_vals["Billed Duration"])
        output.billing.memory = int(aws_vals["Memory Size"])
        output.billing.gb_seconds = output.billing.billed_time * output.billing.memory

    def shutdown(self) -> None:
        pass

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
                queryString="filter @message like /REPORT/",
                startTime=start_time,
                endTime=end_time,
            )
            query_id = query["queryId"]

            while response is None or response["status"] == "Running":
                logging.info("Waiting for AWS query to complete ...")
                time.sleep(1)
                response = self.logs_client.get_query_results(queryId=query_id)
            if len(response["results"]) == 0:
                logging.info("AWS logs are not yet available, repeat ...")
                response = None
                break
            else:
                break
        print(response)

    def download_metrics(
        self,
        function_name: str,
        deployment_config: dict,
        start_time: int,
        end_time: int,
        requests: dict,
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
            startTime=start_time,
            endTime=end_time,
        )
        query_id = query["queryId"]
        response = None

        while response is None or response["status"] == "Running":
            logging.info("Waiting for AWS query to complete ...")
            time.sleep(1)
            response = self.logs_client.get_query_results(queryId=query_id)
        # results contain a list of matches
        # each match has multiple parts, we look at `@message` since this one
        # contains the report of invocation
        results = response["results"]
        for val in results:
            for result_part in val:
                if result_part["field"] == "@message":
                    actual_result = AWS.parse_aws_report(result_part["value"])
                    request_id = actual_result["REPORT RequestId"]
                    if request_id not in requests:
                        logging.info(
                            "Found invocation {} without result in bucket!".format(
                                request_id
                            )
                        )
                    del actual_result["REPORT RequestId"]
                    requests[request_id][self.name()] = actual_result

    def create_function_copies(
        self,
        benchmark: Benchmark,
        function_names: List[str],
        api_name: str,
        memory: int,
        timeout: int,
        code_package: Benchmark,
        experiment_config: dict,
        api_id: str = None,
    ):

        code_location = code_package.code_location
        code_size = code_package.code_size
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory

        self.get_lambda_client()
        api_client = boto3.client(
            service_name="apigateway",
            aws_access_key_id=self.config.credentials.access_key,
            aws_secret_access_key=self.config.credentials.secret_key,
            region_name=self.config.region,
        )
        # api_name = '{api_name}_API'.format(api_name=api_name)
        if api_id is None:
            api = api_client.create_rest_api(name=api_name)
            api_id = api["id"]
        resource = api_client.get_resources(restApiId=api_id)
        for r in resource["items"]:
            if r["path"] == "/":
                parent_id = r["id"]
        logging.info(
            "Created API {} with id {} and resource parent id {}".format(
                api_name, api_id, parent_id
            )
        )

        # Run AWS-specific part of building code.
        urls = [
            self.create_lambda_function(
                benchmark,
                fname,
                api_id,
                parent_id,
                code_location,
                code_size,
                memory,
                timeout,
                experiment_config,
            )
            for fname in function_names
        ]
        return urls, api_id

    def delete_function(self, function_names: List[str]):
        self.get_lambda_client()
        for fname in function_names:
            try:
                logging.info("Attempting delete")
                self.client.delete_function(FunctionName=fname)
            except Exception:
                pass

    def update_function_config(self, fname: str, timeout: int, memory: int):
        self.get_lambda_client()
        self.client.update_function_configuration(
            FunctionName=fname, Timeout=timeout, MemorySize=memory
        )


class LambdaFunction(Function):
    @property
    def code_package(self):
        return self._code_package

    def __init__(self, name: str, code_package: str, deployment: AWS):
        super().__init__(name)
        self._code_package = code_package
        self._deployment = deployment

    def sync_invoke(self, payload: dict):
        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self._deployment.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(
            FunctionName=self.name, Payload=serialized_payload, LogType="Tail"
        )
        end = datetime.datetime.now()

        aws_result = ExecutionResult(begin, end)
        if ret["StatusCode"] != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self._deployment.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self._deployment.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        log = base64.b64decode(ret["LogResult"])
        function_output = json.loads(ret["Payload"].read().decode("utf-8"))

        # AWS-specific parsing
        AWS.parse_aws_report(log.decode("utf-8"), aws_result)
        # General benchmark output parsing
        # For some reason, the body is dict for NodeJS but a serialized JSON for Python
        if isinstance(function_output["body"], dict):
            aws_result.parse_benchmark_output(function_output["body"])
        else:
            aws_result.parse_benchmark_output(json.loads(function_output["body"]))
        return aws_result

    def async_invoke(self, payload: dict):

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self._deployment.get_lambda_client()
        ret = client.invoke(
            FunctionName=self.name,
            InvocationType="Event",
            Payload=serialized_payload,
            LogType="Tail",
        )
        if ret["StatusCode"] != 202:
            logging.error("Async invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            raise RuntimeError()
        return ret

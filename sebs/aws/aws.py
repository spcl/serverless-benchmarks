import base64
import datetime
import json
import logging
import os
import shutil
import time
import uuid
from typing import List, Tuple

import boto3

from .. import utils
from ..code_package import CodePackage
from .s3 import S3


class classproperty(property):
    def __get__(self, cls, owner):
        return classmethod(self.fget).__get__(None, owner)()


class AWS:
    client = None
    logs_client = None
    cache_client = None
    docker_client = None
    config = None
    storage = None
    language = None
    cached = False

    # AWS credentials
    access_key = None
    secret_key = None

    @classproperty
    def name(cls):
        return "aws"

    """
        :param cache_client: Function cache instance
        :param config: Experiments config
        :param language: Programming language to use for functions
        :param docker_client: Docker instance
    """

    def __init__(self, cache_client, config, language, docker_client):
        self.config = config
        self.language = language
        self.cache_client = cache_client
        self.docker_client = docker_client

    """
        Parse AWS credentials passed in config or environment variables.
        Updates class properties.
    """

    def configure_credentials(self):
        if self.access_key is None:
            # Verify we can log in
            # 1. Cached credentials
            # TODO: flag to update cache
            if "secrets" in self.config:
                self.access_key = self.config["secrets"]["access_key"]
                self.secret_key = self.config["secrets"]["secret_key"]
            # 2. Environmental variables
            elif "AWS_ACCESS_KEY_ID" in os.environ:
                self.access_key = os.environ["AWS_ACCESS_KEY_ID"]
                self.secret_key = os.environ["AWS_SECRET_ACCESS_KEY"]
                # update
                self.cache_client.update_config(
                    val=self.access_key, keys=["aws", "secrets", "access_key"]
                )
                self.cache_client.update_config(
                    val=self.secret_key, keys=["aws", "secrets", "secret_key"]
                )
            else:
                raise RuntimeError(
                    "AWS login credentials are missing! Please set "
                    "up environmental variables AWS_ACCESS_KEY_ID and "
                    "AWS_SECRET_ACCESS_KEY"
                )

    """
        Start boto3 client for `client` AWS resource.

        :param resource: AWS resource to use
        :param code_package: not used
    """

    def start(self, resource: str = "lambda", code_package=None):

        self.configure_credentials()
        return boto3.client(
            resource,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.config["config"]["region"],
        )

    def start_lambda(self):
        if not self.client:
            self.client = self.start("lambda")

    """
        Create a client instance for cloud storage. When benchmark and buckets
        parameters are passed, then storage is initialized with required number
        of buckets. Buckets may be created or retrieved from cache.

        :param benchmark: benchmark name
        :param buckets: tuple of required input/output buckets
        :param replace_existing: replace existing files in cached buckets?
        :return: storage client
    """

    def get_storage(
        self,
        benchmark: str = None,
        buckets: Tuple[int, int] = None,
        replace_existing: bool = False,
    ):
        self.configure_credentials()
        self.storage = S3(
            self.config["config"]["region"],
            access_key=self.access_key,
            secret_key=self.secret_key,
            replace_existing=replace_existing,
        )
        if benchmark and buckets:
            self.storage.create_buckets(
                benchmark,
                buckets,
                self.cache_client.get_storage_config("aws", benchmark),
            )
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

        dir: directory where code is located
        benchmark: benchmark name
    """

    def package_code(self, directory: str, benchmark: str):

        CONFIG_FILES = {
            "python": ["handler.py", "requirements.txt", ".python_packages"],
            "nodejs": ["handler.js", "package.json", "node_modules"],
        }
        package_config = CONFIG_FILES[self.language]
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
        utils.execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True)
        benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark))
        logging.info("Created {} archive".format(benchmark_archive))

        bytes_size = os.path.getsize(benchmark_archive)
        mbytes = bytes_size / 1024.0 / 1024.0
        logging.info("Zip archive size {:2f} MB".format(mbytes))
        os.chdir(cur_dir)
        return os.path.join(directory, "{}.zip".format(benchmark)), bytes_size

    """
        a)  if a cached function is present and no update flag is passed,
            then just return function name
        b)  if a cached function is present and update flag is passed,
            then upload new code
        c)  if no cached function is present, then create code package and
            either create new function on AWS or update an existing one

        :param benchmark:
        :param benchmark_path: Path to benchmark code
        :param config: JSON config for benchmark
        :param function_name: Override randomly generated function name
        :return: function name, code size
    """

    def create_function(self, code_package: CodePackage, experiment_config: dict):

        benchmark = code_package.benchmark
        if code_package.is_cached and code_package.is_cached_valid:
            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            logging.info(
                "Using cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )
            return func_name
        elif code_package.is_cached:

            func_name = code_package.cached_config["name"]
            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            self.start_lambda()
            # Run AWS-specific part of building code.
            package, code_size = self.package_code(
                code_location, code_package.benchmark
            )
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
                "aws", benchmark, self.language, package, cached_cfg
            )

            logging.info(
                "Updating cached function {fname} in {loc}".format(
                    fname=func_name, loc=code_location
                )
            )

            return func_name
        # no cached instance, create package and upload code
        else:

            code_location = code_package.code_location
            timeout = code_package.benchmark_config["timeout"]
            memory = code_package.benchmark_config["memory"]

            self.start_lambda()

            # Create function name
            func_name = "{}-{}-{}".format(benchmark, self.language, memory)
            # AWS Lambda does not allow hyphens in function names
            func_name = func_name.replace("-", "_")
            func_name = func_name.replace(".", "_")

            # Run AWS-specific part of building code.
            package, code_size = self.package_code(
                code_location, code_package.benchmark
            )

            # we can either check for exception or use list_functions
            # there's no API for test
            language_runtime = self.config["config"]["runtime"][self.language]
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
                if code_size < 50 * 1024 * 1024:
                    package_body = open(package, "rb").read()
                    code_config = {"ZipFile": package_body}
                # Upload code package to S3, then use it
                else:
                    code_package_name = os.path.basename(package)
                    bucket, idx = self.storage.add_input_bucket(benchmark)
                    self.storage.upload(bucket, code_package_name, package)
                    logging.info(
                        "Uploading function {} code to {}".format(func_name, bucket)
                    )
                    code_config = {"S3Bucket": bucket, "S3Key": code_package_name}
                self.client.create_function(
                    FunctionName=func_name,
                    Runtime="{}{}".format(self.language, language_runtime),
                    Handler="handler.handler",
                    Role=self.config["config"]["lambda-role"],
                    MemorySize=memory,
                    Timeout=timeout,
                    Code=code_config,
                )
                url = self.create_http_trigger(func_name, None, None)

            self.cache_client.add_function(
                deployment="aws",
                benchmark=benchmark,
                language=self.language,
                code_package=package,
                language_config={
                    "name": func_name,
                    "code_size": code_size,
                    "runtime": language_runtime,
                    "role": self.config["config"]["lambda-role"],
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
            return func_name

    def create_http_trigger(self, func_name: str, api_id: str, parent_id: str):

        # https://github.com/boto/boto3/issues/572
        # assumed we have: function name, region

        api_client = self.start("apigateway")

        # create REST API
        if api_id is None:
            api_name = func_name
            api = api_client.create_rest_api(name=api_name)
            api_id = api["id"]
        if parent_id is None:
            resource = api_client.get_resources(restApiId=api_id)
            for r in resource["items"]:
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
                restApiId=api_id, parentId=parent_id, pathPart=func_name
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
        sts_client = self.start("sts")
        account_id = sts_client.get_caller_identity()["Account"]

        uri_data = {
            "aws-region": self.config["config"]["region"],
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
            code_body = open(code_package, "rb").read()
            self.client.update_function_code(FunctionName=name, ZipFile=code_body)
        # Upload code package to S3, then update
        else:
            code_package_name = os.path.basename(code_package)
            bucket, idx = self.storage.add_input_bucket(benchmark)
            self.storage.upload(bucket, code_package_name, code_package)
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

    def invoke_sync(self, name: str, payload: dict):

        self.start_lambda()
        payload = json.dumps(payload).encode("utf-8")
        begin = datetime.datetime.now()
        ret = self.client.invoke(FunctionName=name, Payload=payload, LogType="Tail")
        end = datetime.datetime.now()

        if ret["StatusCode"] != 200:
            logging.error("Invocation of {} failed!".format(name))
            logging.error("Input: {}".format(payload.decode("utf-8")))
            self.get_invocation_error(
                function_name=name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            raise RuntimeError()
        if "FunctionError" in ret:
            logging.error("Invocation of {} failed!".format(name))
            logging.error("Input: {}".format(payload.decode("utf-8")))
            self.get_invocation_error(
                function_name=name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            raise RuntimeError()
        log = base64.b64decode(ret["LogResult"])
        vals = {}
        vals["aws"] = AWS.parse_aws_report(log.decode("utf-8"))
        ret = json.loads(ret["Payload"].read().decode("utf-8"))
        vals["client_time"] = (end - begin) / datetime.timedelta(microseconds=1)
        vals["return"] = ret
        return vals

    def invoke_async(self, name: str, payload: dict):

        ret = self.client.invoke(
            FunctionName=name, InvocationType="Event", Payload=payload, LogType="Tail"
        )
        if ret["StatusCode"] != 202:
            logging.error("Async invocation of {} failed!".format(name))
            logging.error("Input: {}".format(payload.decode("utf-8")))
            raise RuntimeError()

    """
        Accepts AWS report after function invocation.
        Returns a dictionary filled with values with various metrics such as
        time, invocation time and memory consumed.

        :param log: decoded log from CloudWatch or from synchronuous invocation
        :return: dictionary with parsed values
    """

    def parse_aws_report(log: str):
        aws_vals = {}
        for line in log.split("\t"):
            if not line.isspace():
                split = line.split(":")
                aws_vals[split[0]] = split[1].split()[0]
        return aws_vals

    def shutdown(self):
        pass

    def get_invocation_error(self, function_name: str, start_time: int, end_time: int):
        self.configure_credentials()
        if not self.logs_client:
            self.logs_client = self.start("logs")

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

        self.configure_credentials()
        if not self.logs_client:
            self.logs_client = self.start("logs")

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
                    requests[request_id]["aws"] = actual_result

    def create_lambda_function(
        self,
        function_name: str,
        api_id: str,
        parent_id: str,
        package: str,
        code_size: int,
        memory: int,
        timeout: int,
        experiment_config: dict,
    ):

        language_runtime = self.config["config"]["runtime"][self.language]
        logging.info("Creating function {} from {}".format(function_name, package))

        # TODO: create Lambda role
        # AWS Lambda limit on zip deployment size
        # Limit to 50 MB
        if code_size < 50 * 1024 * 1024:
            package_body = open(package, "rb").read()
            code_config = {"ZipFile": package_body}
        # Upload code package to S3, then use it
        else:
            code_package_name = os.path.basename(package)
            bucket, idx = self.storage.add_input_bucket(function_name)
            self.storage.upload(bucket, code_package_name, package)
            logging.info(
                "Uploading function {} code to {}".format(function_name, bucket)
            )
            code_config = {"S3Bucket": bucket, "S3Key": code_package_name}
        self.client.create_function(
            FunctionName=function_name,
            Runtime="{}{}".format(self.language, language_runtime),
            Handler="handler.handler",
            Role=self.config["config"]["lambda-role"],
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
                api_client = self.start("apigateway")
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

    def create_function_copies(
        self,
        function_names: List[str],
        api_name: str,
        memory: int,
        timeout: int,
        code_package: CodePackage,
        experiment_config: dict,
        api_id: str = None,
    ):

        code_location = code_package.code_location
        code_size = code_package.code_size
        timeout = code_package.benchmark_config["timeout"]
        memory = code_package.benchmark_config["memory"]

        self.start_lambda()
        api_client = self.start("apigateway")
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
        self.start_lambda()
        for fname in function_names:
            try:
                logging.info("Attempting delete")
                self.client.delete_function(FunctionName=fname)
            except Exception:
                pass

    def update_function_config(self, fname: str, timeout: int, memory: int):
        self.start_lambda()
        self.client.update_function_configuration(
            FunctionName=fname, Timeout=timeout, MemorySize=memory
        )

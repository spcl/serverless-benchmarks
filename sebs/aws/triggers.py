import base64
import concurrent.futures
import datetime
import json
from typing import Optional
import uuid  # noqa

import boto3

from sebs.aws.aws import AWS
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[AWS] = None):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "AWS.LibraryTrigger"

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.name}")

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(FunctionName=self.name, Payload=serialized_payload, LogType="Tail")
        end = datetime.datetime.now()

        aws_result = ExecutionResult.from_times(begin, end)
        aws_result.request_id = ret["ResponseMetadata"]["RequestId"]
        if ret["StatusCode"] != 200:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            self.logging.error("Invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            aws_result.stats.failure = True
            return aws_result
        self.logging.debug(f"Invoke of function {self.name} was successful")
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

        # FIXME: proper return type
        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        ret = client.invoke(
            FunctionName=self.name,
            InvocationType="Event",
            Payload=serialized_payload,
            LogType="Tail",
        )
        if ret["StatusCode"] != 202:
            self.logging.error("Async invocation of {} failed!".format(self.name))
            self.logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            raise RuntimeError()
        return ret

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    def __init__(self, url: str, api_id: str):
        super().__init__()
        self.url = url
        self.api_id = api_id

    @staticmethod
    def typename() -> str:
        return "AWS.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url, "api-id": self.api_id}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"], obj["api-id"])


class QueueTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        deployment_client: Optional[AWS] = None,
        queue_arn: Optional[str] = None,
        queue_url: Optional[str] = None,
    ):
        super().__init__()
        self.name = fname

        self._deployment_client = None
        self._queue_arn = None
        self._queue_url = None

        if deployment_client:
            self._deployment_client = deployment_client
        if queue_arn:
            self._queue_arn = queue_arn
        if queue_url:
            self._queue_url = queue_url

        # When creating the trigger for the first time, also create and store
        # queue information.
        if not self.queue_arn and not self.queue_url:
            # Init clients
            lambda_client = self.deployment_client.get_lambda_client()
            sqs_client = boto3.client("sqs", region_name=self.deployment_client.config.region)

            # Create queue
            self.logging.debug(f"Creating queue {self.name}")

            self._queue_url = sqs_client.create_queue(QueueName=self.name)["QueueUrl"]
            self._queue_arn = sqs_client.get_queue_attributes(
                QueueUrl=self.queue_url, AttributeNames=["QueueArn"]
            )["Attributes"]["QueueArn"]

            self.logging.debug("Created queue")

            # Add queue trigger
            if not len(
                lambda_client.list_event_source_mappings(
                    EventSourceArn=self.queue_arn, FunctionName=self.name
                )["EventSourceMappings"]
            ):
                lambda_client.create_event_source_mapping(
                    EventSourceArn=self.queue_arn,
                    FunctionName=self.name,
                    MaximumBatchingWindowInSeconds=1,
                )

    @staticmethod
    def typename() -> str:
        return "AWS.QueueTrigger"

    @property
    def queue_arn(self) -> str:
        assert self._queue_arn
        return self._queue_arn

    @property
    def queue_url(self) -> str:
        assert self._queue_url
        return self._queue_url

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.QUEUE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.name}")

        sqs_client = boto3.client("sqs", region_name=self.deployment_client.config.region)

        # Publish payload to queue
        serialized_payload = json.dumps(payload)
        sqs_client.send_message(QueueUrl=self.queue_url, MessageBody=serialized_payload)
        self.logging.info(f"Sent message to queue {self.name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Queue",
            "name": self.name,
            "queue_arn": self.queue_arn,
            "queue_url": self.queue_url,
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(obj["name"], None, obj["queue_arn"], obj["queue_url"])


class StorageTrigger(Trigger):
    def __init__(
        self, fname: str, deployment_client: Optional[AWS] = None, bucket_name: Optional[str] = None
    ):
        super().__init__()
        self.name = fname

        self._deployment_client = None
        self._bucket_name = None

        if deployment_client:
            self._deployment_client = deployment_client
        if bucket_name:
            self._bucket_name = bucket_name

        # When creating the trigger for the first time, also create and store
        # storage bucket information.
        if not self.bucket_name:
            # Init clients
            s3 = boto3.resource("s3")
            lambda_client = self.deployment_client.get_lambda_client()

            # AWS disallows underscores in bucket names
            self._bucket_name = self.name.replace("_", "-")
            function_arn = lambda_client.get_function(FunctionName=self.name)["Configuration"][
                "FunctionArn"
            ]

            # Create bucket
            self.logging.info(f"Creating bucket {self.bucket_name}")

            region = self.deployment_client.config.region
            if region == "us-east-1":
                s3.create_bucket(Bucket=self.bucket_name)
            else:
                s3.create_bucket(
                    Bucket=self.bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )

            self.logging.info("Created bucket")

            lambda_client.add_permission(
                FunctionName=self.name,
                StatementId=str(uuid.uuid1()),
                Action="lambda:InvokeFunction",
                Principal="s3.amazonaws.com",
                SourceArn=f"arn:aws:s3:::{self.bucket_name}",
            )

            # Add bucket trigger
            bucket_notification = s3.BucketNotification(self.bucket_name)
            bucket_notification.put(
                NotificationConfiguration={
                    "LambdaFunctionConfigurations": [
                        {
                            "LambdaFunctionArn": function_arn,
                            "Events": ["s3:ObjectCreated:*"],
                        },
                    ]
                }
            )

    @staticmethod
    def typename() -> str:
        return "AWS.StorageTrigger"

    @property
    def bucket_name(self) -> str:
        assert self._bucket_name
        return self._bucket_name

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.name}")

        serialized_payload = json.dumps(payload)

        # Put object
        s3 = boto3.resource("s3")
        s3.Object(self.bucket_name, "payload.json").put(Body=serialized_payload)
        self.logging.info(f"Uploaded payload to bucket {self.bucket_name}")

        # TODO(oana): gather metrics

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {"type": "Storage", "name": self.name, "bucket_name": self.bucket_name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(obj["name"], None, obj["bucket_name"])

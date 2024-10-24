import base64
import concurrent.futures
import datetime
import json
from typing import Optional
import uuid  # noqa

import boto3

from sebs.aws.aws import AWS
from sebs.aws.queue import SQS
from sebs.faas.function import ExecutionResult, Trigger
from sebs.faas.queue import QueueType


class LibraryTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        deployment_client: Optional[AWS] = None,
        application_name: Optional[str] = None,
        result_queue: Optional[SQS] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__()
        self.name = fname
        self._deployment_client = deployment_client
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = SQS(
                f'{application_name}-result',
                QueueType.RESULT,
                self.deployment_client.config.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def typename() -> str:
        return "AWS.LibraryTrigger"

    @property
    def result_queue(self) -> SQS:
        assert self._result_queue
        return self._result_queue

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
        return {
            "type": "Library",
            "name": self.name,
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(
            obj["name"],
            None,
            SQS.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            obj["with_result_queue"]
        )


class HTTPTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        url: str,
        api_id: str,
        application_name: Optional[str] = None,
        result_queue: Optional[SQS] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__()
        self.name = fname
        self.url = url
        self.api_id = api_id
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = SQS(
                f'{application_name}-result',
                QueueType.RESULT,
                self.deployment_client.config.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def typename() -> str:
        return "AWS.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    @property
    def result_queue(self) -> SQS:
        assert self._result_queue
        return self._result_queue

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        self.logging.debug(f"Invoke function {self.url}")
        return self._http_invoke(payload, self.url)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "HTTP",
            "name": self.name,
            "url": self.url,
            "api-id": self.api_id,
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(
            obj["name"],
            obj["url"],
            obj["api-id"],
            SQS.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            obj["with_result_queue"]
        )


class QueueTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        deployment_client: Optional[AWS] = None,
        queue: Optional[SQS] = None,
        application_name: Optional[str] = None,
        result_queue: Optional[SQS] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__()
        self.name = fname
        self._queue = queue
        self._result_queue = result_queue
        self._deployment_client = deployment_client
        self.with_result_queue = with_result_queue

        if (not self._queue):
            self._queue = SQS(
                self.name,
                QueueType.TRIGGER,
                self.deployment_client.config.region                
            )
            self.queue.create_queue()

            # Add queue trigger
            lambda_client = self.deployment_client.get_lambda_client()
            if not len(
                lambda_client.list_event_source_mappings(
                    EventSourceArn=self.queue.queue_arn, FunctionName=self.name
                )["EventSourceMappings"]
            ):
                lambda_client.create_event_source_mapping(
                    EventSourceArn=self.queue.queue_arn,
                    FunctionName=self.name,
                    Enabled=True,
                    BatchSize=1,
                    MaximumBatchingWindowInSeconds=1,
                )

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = SQS(
                f'{application_name}-result',
                QueueType.RESULT,
                self.deployment_client.config.region
            )
            self._result_queue.create_queue()

    @staticmethod
    def typename() -> str:
        return "AWS.QueueTrigger"

    @property
    def queue(self) -> SQS:
        assert self._queue
        return self._queue

    @property
    def result_queue(self) -> SQS:
        assert self._result_queue
        return self._result_queue

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

        # Publish payload to queue
        serialized_payload = json.dumps(payload)
        begin = datetime.datetime.now()
        self.queue.send_message(serialized_payload)

        results = self.collect_async_results(self.result_queue)

        ret = []
        for recv_ts, result_data in results.items():
            result = ExecutionResult.from_times(begin, recv_ts)
            result.parse_benchmark_output(result_data)
            ret.append(result)

        return ret

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Queue",
            "name": self.name,
            "queue": self.queue.serialize(),
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return QueueTrigger(
            obj["name"],
            None,
            SQS.deserialize(obj["queue"]),
            SQS.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            obj["with_result_queue"]
        )


class StorageTrigger(Trigger):
    def __init__(
        self,
        fname: str,
        deployment_client: Optional[AWS] = None,
        bucket_name: Optional[str] = None,
        application_name: Optional[str] = None,
        result_queue: Optional[SQS] = None,
        with_result_queue: Optional[bool] = False
    ):
        super().__init__()
        self.name = fname

        self._deployment_client = deployment_client
        self._bucket_name = bucket_name
        self._result_queue = result_queue
        self.with_result_queue = with_result_queue

        # When creating the trigger for the first time, also create and store
        # storage bucket information.
        if not self._bucket_name:
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

        # Create result queue for communicating benchmark results back to the
        # client.
        if (self.with_result_queue and not self._result_queue):
            self._result_queue = SQS(
                f'{application_name}-result',
                QueueType.RESULT,
                self.deployment_client.config.region
            )
            self._result_queue.create_queue()

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

    @property
    def result_queue(self) -> SQS:
        assert self._result_queue
        return self._result_queue

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
        begin = datetime.datetime.now()
        s3.Object(self.bucket_name, "payload.json").put(Body=serialized_payload)
        self.logging.info(f"Uploaded payload to bucket {self.bucket_name}")

        results = self.collect_async_results(self.result_queue)

        ret = []
        for recv_ts, result_data in results.items():
            result = ExecutionResult.from_times(begin, recv_ts)
            result.parse_benchmark_output(result_data)
            ret.append(result)

        return ret

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:

        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": "Storage",
            "name": self.name,
            "bucket_name": self.bucket_name,
            "result_queue": self._result_queue.serialize() if self._result_queue else "",
            "with_result_queue": self.with_result_queue
        }

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(
            fname=obj["name"],
            bucket_name=obj["bucket_name"],
            result_queue=SQS.deserialize(obj["result_queue"]) if obj["result_queue"] != "" else None,
            with_result_queue=obj["with_result_queue"]
        )

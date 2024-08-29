from sebs.cache import Cache
from sebs.faas.config import Resources
from sebs.faas.queue import Queue

import boto3


class SQS(Queue):
    @staticmethod
    def typename() -> str:
        return "AWS.SQS"

    @staticmethod
    def deployment_name():
        return "aws"

    @property
    def queue_url(self):
        return self._queue_url

    def __init__(
        self,
        benchmark: str,
        queue_type: Queue.QueueType,
        session: boto3.session.Session,
        cache_client: Cache,
        resources: Resources,
        region: str
    ):
        super().__init__(benchmark, queue_type, region, cache_client, resources)
        self.client = session.client(
            "sqs",
            region_name=region,
        )

    def create_queue(self) -> str:
        self.logging.debug(f"Creating queue {self.name}")

        self._queue_url = self.client.create_queue(QueueName=self.name)["QueueUrl"]
        queue_arn = self.client.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["QueueArn"],
        )["Attributes"]["QueueArn"]

        self.logging.debug("Created queue")

        if (self.queue_type == Queue.QueueType.TRIGGER):
            # Make it an actual trigger for the function. GCP and Azure use
            # different mechanisms so this is skipped for them.
            if (not len(self.client.list_event_source_mappings(EventSourceArn=queue_arn,
                                                                FunctionName=self.name)
                        ["EventSourceMappings"])):
                self.client.create_event_source_mapping(
                    EventSourceArn=queue_arn,
                    FunctionName=self.name,
                    MaximumBatchingWindowInSeconds=1,
                )

    def remove_queue(self):
        self.logging.info(f"Deleting queue {self.name}")

        self.client.delete_queue(QueueUrl=self.queue_url)

        self.logging.info("Deleted queue")

    def send_message(self, serialized_message: str):
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=serialized_message,
        )
        self.logging.info(f"Sent message to queue {self.name}")

    def receive_message(self) -> str:
        self.logging.info(f"Pulling a message from {self.name}")

        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MessageSystemAttributeNames=["SentTimestamp"],
            MaxNumberOfMessages=1,
            MessageAttributeNames=["All"],
            WaitTimeSeconds=5,
        )

        if ("Messages" not in response):
            self.logging.info("No messages to be received")
            return

        self.logging.info(f"Received a message from {self.name}")
        return response["Messages"][0]["Body"]
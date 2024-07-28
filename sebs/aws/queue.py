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
            region_name=region
        )

    def create_queue(self) -> str:
        # Create queue
        self.logging.debug(f"Creating queue {self.name}")

        self._queue_url = self.client.create_queue(QueueName=self.name)["QueueUrl"]
        queue_arn = self.client.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]

        self.logging.debug("Created queue")

        if (self.queue_type == Queue.QueueType.TRIGGER):
            # Add queue trigger
            if (not len(self.client.list_event_source_mappings(EventSourceArn=queue_arn,
                                                                FunctionName=self.name)
                        ["EventSourceMappings"])):
                self.client.create_event_source_mapping(
                    EventSourceArn=queue_arn,
                    FunctionName=self.name,
                    MaximumBatchingWindowInSeconds=1
                )

    def remove_queue(self):
        raise NotImplementedError()

    def send_message(self, serialized_message: str):
        self.client.send_message(
            QueueUrl=self.queue_url, MessageBody=serialized_message)
        self.logging.info(f"Sent message to queue {self.name}")

    def receive_message(self) -> str:
        raise NotImplementedError()
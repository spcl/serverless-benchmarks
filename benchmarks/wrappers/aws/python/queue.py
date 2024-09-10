import boto3

class queue:
    client = None

    def __init__(self, queue_name: str, account_id: str, region: str):
        self.client = boto3.client('sqs', region_name=region)
        self.queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"

    def send_message(self, message: str):
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=message,
        )

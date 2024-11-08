import boto3, os

class queue:
    client = None

    def __init__(self, queue_name: str):
        account_id = os.getenv('ACCOUNT_ID')
        region = os.getenv('REGION')
    
        self.client = boto3.client('sqs', region_name=region)
        self.queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"

    def send_message(self, message: str):
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=message,
        )

from google.cloud import pubsub_v1

class queue:
    client = None

    def __init__(self, topic_name: str, project_id: str):
        self.client = pubsub_v1.PublisherClient()
        self.topic_name = 'projects/{project_id}/topics/{topic}'.format(
            project_id=project_id,
            topic=topic_name,
        )

    def send_message(self, message: str):
        self.client.publish(self.topic_name, message.encode("utf-8"))

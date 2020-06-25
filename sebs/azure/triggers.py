from sebs.faas.function import ExecutionResult, Trigger


class HTTPTrigger(Trigger):
    def __init__(self, url: str):
        self.url = url

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def async_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def serialize(self) -> dict:
        return {"type": "HTTP", "url": self.url}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return HTTPTrigger(obj["url"])

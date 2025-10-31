from typing import Optional

from sebs.faas.function import Trigger


class LibraryTrigger(Trigger):
    """
    Library trigger for Cloudflare Workers.
    Allows invoking workers programmatically via the Cloudflare API.
    """
    
    def __init__(self, worker_name: str, deployment_client=None):
        super().__init__(worker_name)
        self.deployment_client = deployment_client

    @staticmethod
    def typename() -> str:
        return "Cloudflare.LibraryTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> Optional[str]:
        """
        Synchronously invoke a Cloudflare Worker.
        
        Args:
            payload: The payload to send to the worker
            
        Returns:
            The response from the worker
        """
        # This will be implemented when we have the deployment client
        raise NotImplementedError("Cloudflare Worker invocation not yet implemented")

    def async_invoke(self, payload: dict) -> object:
        """
        Asynchronously invoke a Cloudflare Worker.
        Not typically supported for Cloudflare Workers.
        """
        raise NotImplementedError("Cloudflare Workers do not support async invocation")

    def serialize(self) -> dict:
        return {**super().serialize()}

    @staticmethod
    def deserialize(obj: dict) -> "LibraryTrigger":
        return LibraryTrigger(obj["name"])


class HTTPTrigger(Trigger):
    """
    HTTP trigger for Cloudflare Workers.
    Workers are automatically accessible via HTTPS endpoints.
    """
    
    def __init__(self, worker_name: str, url: Optional[str] = None):
        super().__init__(worker_name)
        self._url = url

    @staticmethod
    def typename() -> str:
        return "Cloudflare.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    @property
    def url(self) -> str:
        assert self._url is not None, "HTTP trigger URL has not been set"
        return self._url

    @url.setter
    def url(self, url: str):
        self._url = url

    def sync_invoke(self, payload: dict) -> Optional[str]:
        """
        Synchronously invoke a Cloudflare Worker via HTTP.
        
        Args:
            payload: The payload to send to the worker
            
        Returns:
            The response from the worker
        """
        import requests
        
        response = requests.post(self.url, json=payload)
        response.raise_for_status()
        return response.text

    def async_invoke(self, payload: dict) -> object:
        """
        Asynchronously invoke a Cloudflare Worker via HTTP.
        Not typically needed for Cloudflare Workers.
        """
        raise NotImplementedError("Cloudflare Workers do not support async HTTP invocation")

    def serialize(self) -> dict:
        return {
            **super().serialize(),
            "url": self._url,
        }

    @staticmethod
    def deserialize(obj: dict) -> "HTTPTrigger":
        trigger = HTTPTrigger(obj["name"])
        if "url" in obj:
            trigger.url = obj["url"]
        return trigger

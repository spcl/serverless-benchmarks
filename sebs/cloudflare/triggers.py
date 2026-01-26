from typing import Optional
import concurrent.futures

from sebs.faas.function import Trigger, ExecutionResult


class HTTPTrigger(Trigger):
    """
    HTTP trigger for Cloudflare Workers.
    Workers are automatically accessible via HTTPS endpoints.
    """
    
    def __init__(self, worker_name: str, url: Optional[str] = None):
        super().__init__()
        self.worker_name = worker_name
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

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke a Cloudflare Worker via HTTP.
        
        Args:
            payload: The payload to send to the worker
            
        Returns:
            ExecutionResult with performance metrics extracted from the response
        """
        self.logging.debug(f"Invoke function {self.url}")
        result = self._http_invoke(payload, self.url)
        
        # Extract measurement data from the response if available
        if result.output and 'result' in result.output:
            result_data = result.output['result']
            if isinstance(result_data, dict) and 'measurement' in result_data:
                measurement = result_data['measurement']
                
                # Extract timing metrics if provided by the benchmark
                if isinstance(measurement, dict):
                    # CPU time in microseconds
                    if 'cpu_time_us' in measurement:
                        result.provider_times.execution = measurement['cpu_time_us']
                    elif 'cpu_time_ms' in measurement:
                        result.provider_times.execution = int(measurement['cpu_time_ms'] * 1000)
                    
                    # Wall time in microseconds
                    if 'wall_time_us' in measurement:
                        result.times.benchmark = measurement['wall_time_us']
                    elif 'wall_time_ms' in measurement:
                        result.times.benchmark = int(measurement['wall_time_ms'] * 1000)
                    
                    # Cold/warm start detection
                    if 'is_cold' in measurement:
                        result.stats.cold_start = measurement['is_cold']
                    
                    # Memory usage if available
                    if 'memory_used_mb' in measurement:
                        result.stats.memory_used = measurement['memory_used_mb']
                    
                    # Store the full measurement for later analysis
                    result.output['measurement'] = measurement
                    
                    self.logging.debug(f"Extracted measurements: {measurement}")
        
        return result

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        """
        Asynchronously invoke a Cloudflare Worker via HTTP.
        """
        pool = concurrent.futures.ThreadPoolExecutor()
        fut = pool.submit(self.sync_invoke, payload)
        return fut

    def serialize(self) -> dict:
        return {
            "type": self.typename(),
            "worker_name": self.worker_name,
            "url": self._url,
        }

    @staticmethod
    def deserialize(obj: dict) -> "HTTPTrigger":
        trigger = HTTPTrigger(obj["worker_name"], obj.get("url"))
        return trigger

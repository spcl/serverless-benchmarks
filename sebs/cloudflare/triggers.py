from typing import Optional
import concurrent.futures
import json
from datetime import datetime
from io import BytesIO

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

    def _http_invoke(self, payload: dict, url: str, verify_ssl: bool = True) -> ExecutionResult:
        """
        Invoke a Cloudflare Worker via HTTP POST.

        Overrides the base implementation to add a browser-like User-Agent header.
        Cloudflare's bot-protection returns HTTP 1010 for requests that look like
        automated tools (empty or libcurl User-Agent), so we must set one explicitly.
        """
        import pycurl

        c = pycurl.Curl()
        c.setopt(pycurl.HTTPHEADER, [
            "Content-Type: application/json",
            # Cloudflare bot-protection (error 1010) blocks requests with no/tool UA.
            "User-Agent: Mozilla/5.0 (compatible; SeBS/1.0; +https://github.com/spcl/serverless-benchmarks)",
        ])
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, url)
        if not verify_ssl:
            c.setopt(pycurl.SSL_VERIFYHOST, 0)
            c.setopt(pycurl.SSL_VERIFYPEER, 0)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)

        c.setopt(pycurl.POSTFIELDS, json.dumps(payload))
        begin = datetime.now()
        c.perform()
        end = datetime.now()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        conn_time = c.getinfo(pycurl.PRETRANSFER_TIME)
        receive_time = c.getinfo(pycurl.STARTTRANSFER_TIME)
        c.close()

        try:
            output = json.loads(data.getvalue())
            if "body" in output:
                if isinstance(output["body"], dict):
                    output = output["body"]
                else:
                    output = json.loads(output["body"])

            if status_code != 200:
                self.logging.error(f"Invocation on URL {url} failed!")
                self.logging.error(f"Output: {output}")
                raise RuntimeError(f"Failed invocation of function! Output: {output}")

            self.logging.debug("Invoke of function was successful")
            result = ExecutionResult.from_times(begin, end)
            result.times.http_startup = conn_time
            result.times.http_first_byte_return = receive_time
            if "request_id" not in output:
                raise RuntimeError(f"Cannot process allocation with output: {output}")
            result.request_id = output["request_id"]
            result.parse_benchmark_output(output)
            return result
        except json.decoder.JSONDecodeError:
            self.logging.error(f"Invocation on URL {url} failed!")
            raw = data.getvalue()
            if raw:
                self.logging.error(f"Output: {raw.decode()}")
            else:
                self.logging.error("No output provided!")
            raise RuntimeError(f"Failed invocation of function! Output: {raw.decode()}")

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Synchronously invoke a Cloudflare Worker via HTTP."""
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

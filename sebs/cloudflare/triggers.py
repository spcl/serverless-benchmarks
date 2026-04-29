"""HTTP trigger implementation for Cloudflare Workers."""

from typing import Optional
import concurrent.futures
import json
import time
from datetime import datetime
from io import BytesIO

from sebs.faas.function import Trigger, ExecutionResult


class ContainerProvisioningError(RuntimeError):
    """Raised when Cloudflare reports the container is still provisioning."""

    pass


class HTTPTrigger(Trigger):
    """
    HTTP trigger for Cloudflare Workers.
    Workers are automatically accessible via HTTPS endpoints.
    """

    def __init__(self, worker_name: str, url: Optional[str] = None):
        """Initialize the HTTP trigger with the worker name and optional URL."""
        super().__init__()
        self.worker_name = worker_name
        self._url = url

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this trigger class."""
        return "Cloudflare.HTTPTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the trigger type enum value."""
        return Trigger.TriggerType.HTTP

    @property
    def url(self) -> str:
        """HTTPS endpoint URL for invoking the worker."""
        assert self._url is not None, "HTTP trigger URL has not been set"
        return self._url

    @url.setter
    def url(self, url: str):
        """Set the HTTPS endpoint URL for the worker."""
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
        c.setopt(
            pycurl.HTTPHEADER,
            [
                "Content-Type: application/json",
                # Cloudflare bot-protection (error 1010) blocks requests with no/tool UA.
                "User-Agent: Mozilla/5.0 (compatible; SeBS/1.0; "
                "+https://github.com/spcl/serverless-benchmarks)",
            ],
        )
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

            if status_code == 502:
                self.logging.info("Container returned 502 (still starting?), will retry...")
                raise ContainerProvisioningError("502 gateway error from container worker")

            # Check for Cloudflare error code 1042 (CPU time limit / worker not ready)
            # Output may be a plain string like "error code: 1042" rather than a dict.
            output_str = str(output)
            if "1042" in output_str and "error code" in output_str:
                self.logging.info("Worker returned error 1042 (CPU time limit), will retry...")
                raise ContainerProvisioningError(f"Error 1042 from worker: {output_str}")

            container_not_ready_phrases = (
                "The container is not running",
                "Failed to start container",
            )
            if any(p in output_str for p in container_not_ready_phrases):
                self.logging.info("Container not yet running, will retry...")
                raise ContainerProvisioningError(f"Container startup error: {output_str[:200]}")

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
            raw = data.getvalue()
            raw_text = raw.decode() if raw else ""
            provisioning_phrases = (
                "no Container instance available",
                "provisioning the Container",
                "currently provisioning",
                "The container is not running",
                "Failed to start container",
            )
            if "1042" in raw_text and "error code" in raw_text:
                self.logging.info("Worker returned error 1042 (CPU time limit), will retry...")
                raise ContainerProvisioningError(f"Error 1042 from worker: {raw_text[:200]}")
            if status_code == 502 or any(
                p.lower() in raw_text.lower() for p in provisioning_phrases
            ):
                self.logging.info(f"Container still provisioning (URL {url}): {raw_text[:120]}")
                raise ContainerProvisioningError(f"Container not yet available: {raw_text[:200]}")
            self.logging.error(f"Invocation on URL {url} failed!")
            if raw_text:
                self.logging.error(f"Output: {raw_text}")
            else:
                self.logging.error("No output provided!")
            raise RuntimeError(f"Failed invocation of function! Output: {raw_text}")

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """
        Synchronously invoke a Cloudflare Worker via HTTP.

        Retries on ContainerProvisioningError to cover the short gap between the /health
        check passing (Worker + Durable Object up) and the benchmark handler being fully
        ready.  The /health gate in containers.py absorbs the unpredictable bulk of
        container startup; the retry budget here only needs to bridge the remaining,
        much shorter window.
        """
        self.logging.debug(f"Invoke function {self.url}")
        max_provisioning_retries = 10
        provisioning_retry_wait = 60  # seconds between retries
        for attempt in range(max_provisioning_retries + 1):
            try:
                result = self._http_invoke(payload, self.url)
                break
            except ContainerProvisioningError:
                if attempt < max_provisioning_retries:
                    self.logging.info(
                        f"Container still provisioning, waiting {provisioning_retry_wait}s "
                        f"before retry (attempt {attempt + 1}/{max_provisioning_retries})..."
                    )
                    time.sleep(provisioning_retry_wait)
                else:
                    raise

        # Extract measurement data from the response if available
        if result.output and "result" in result.output:  # type: ignore[union-attr]
            result_data = result.output["result"]
            if isinstance(result_data, dict) and "measurement" in result_data:
                measurement = result_data["measurement"]

                # Extract timing metrics if provided by the benchmark
                if isinstance(measurement, dict):
                    # CPU time in microseconds
                    if "cpu_time_us" in measurement:
                        result.provider_times.execution = measurement["cpu_time_us"]
                    elif "cpu_time_ms" in measurement:
                        result.provider_times.execution = int(measurement["cpu_time_ms"] * 1000)

                    # Wall time in microseconds
                    if "wall_time_us" in measurement:
                        result.times.benchmark = measurement["wall_time_us"]
                    elif "wall_time_ms" in measurement:
                        result.times.benchmark = int(measurement["wall_time_ms"] * 1000)

                    # Cold/warm start detection
                    if "is_cold" in measurement:
                        result.stats.cold_start = measurement["is_cold"]

                    # Memory usage if available
                    if "memory_used_mb" in measurement:
                        result.stats.memory_used = measurement["memory_used_mb"]

                    # Store the full measurement for later analysis
                    result.output["measurement"] = measurement

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
        """Return a serializable dict with the trigger type, worker name, and URL."""
        return {
            "type": self.typename(),
            "worker_name": self.worker_name,
            "url": self._url,
        }

    @staticmethod
    def deserialize(obj: dict) -> "HTTPTrigger":
        """Reconstruct an HTTPTrigger from a serialized dict."""
        trigger = HTTPTrigger(obj["worker_name"], obj.get("url"))
        return trigger

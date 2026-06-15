"""Trigger implementations for Cloudflare Workers and Workflows."""

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

        For container workers, the deployment path already waits until an instance
        is running before returning, so provisioning retries here are a last-resort
        safety net only (e.g. the instance was recycled between deployment and the
        first invocation).
        """
        self.logging.debug(f"Invoke function {self.url}")
        max_provisioning_retries = 2
        provisioning_retry_wait = 15  # seconds between retries
        for attempt in range(max_provisioning_retries + 1):
            try:
                result = self._http_invoke(payload, self.url)
                break
            except ContainerProvisioningError:
                if attempt < max_provisioning_retries:
                    self.logging.info(
                        f"Container not yet ready, waiting {provisioning_retry_wait}s "
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


class WorkflowLibraryTrigger(Trigger):
    """Trigger that invokes a Cloudflare Workflow via its orchestrator's HTTP endpoint.

    The orchestrator worker's fetch handler creates a workflow instance and polls
    for completion internally, returning the final result as the HTTP response.
    """

    def __init__(self, workflow_name: str, orchestrator_url: str):
        """Initialize the workflow trigger.

        Args:
            workflow_name: Name of the Cloudflare Workflow.
            orchestrator_url: HTTP URL of the orchestrator worker.
        """
        super().__init__()
        self.workflow_name = workflow_name
        self._orchestrator_url = orchestrator_url

    @staticmethod
    def typename() -> str:
        """Return the canonical type name for this trigger class."""
        return "Cloudflare.WorkflowLibraryTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        """Return the trigger type enum value."""
        return Trigger.TriggerType.LIBRARY

    def _http_get(self, url: str) -> tuple:
        """Perform a GET request and return (status_code, body_bytes)."""
        import pycurl

        c = pycurl.Curl()
        c.setopt(
            pycurl.HTTPHEADER,
            ["User-Agent: Mozilla/5.0 (compatible; SeBS/1.0; "
             "+https://github.com/spcl/serverless-benchmarks)"],
        )
        c.setopt(pycurl.URL, url)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)
        c.setopt(pycurl.TIMEOUT, 30)
        c.perform()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        c.close()
        return status_code, data.getvalue()

    def _http_post(self, url: str, body: str) -> tuple:
        """Perform a POST request and return (status_code, body_bytes)."""
        import pycurl

        c = pycurl.Curl()
        c.setopt(
            pycurl.HTTPHEADER,
            [
                "Content-Type: application/json",
                "User-Agent: Mozilla/5.0 (compatible; SeBS/1.0; "
                "+https://github.com/spcl/serverless-benchmarks)",
            ],
        )
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.URL, url)
        data = BytesIO()
        c.setopt(pycurl.WRITEFUNCTION, data.write)
        c.setopt(pycurl.POSTFIELDS, body)
        c.setopt(pycurl.TIMEOUT, 30)
        c.perform()
        status_code = c.getinfo(pycurl.RESPONSE_CODE)
        c.close()
        return status_code, data.getvalue()

    def _do_invoke(self, payload: dict) -> ExecutionResult:
        """Create a workflow instance and poll until completion.

        1. POST to orchestrator → receives {id} (202 Accepted).
        2. GET orchestrator?id=<id> repeatedly until status is complete/errored.
        """
        begin = datetime.now()

        # Step 1: create workflow instance
        max_create_retries = 3
        instance_id = None
        for attempt in range(max_create_retries + 1):
            try:
                status_code, raw = self._http_post(self._orchestrator_url, json.dumps(payload))
            except Exception as e:
                if attempt < max_create_retries:
                    self.logging.warning(f"Workflow creation network error: {e} — retrying")
                    time.sleep(5)
                    continue
                self.logging.error(f"Workflow creation network error after retries: {e}")
                end = datetime.now()
                result = ExecutionResult.from_times(begin, end)
                result.stats.failure = True
                return result
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                text = raw.decode()
                if "1042" in text and "error code" in text:
                    raise ContainerProvisioningError(f"Error 1042 creating workflow: {text[:200]}")
                if attempt < max_create_retries:
                    time.sleep(5)
                    continue
                self.logging.error(
                    f"Workflow creation non-JSON response: {text[:200]}"
                )
                end = datetime.now()
                result = ExecutionResult.from_times(begin, end)
                result.stats.failure = True
                return result

            if status_code == 202 and "id" in resp:
                instance_id = resp["id"]
                break
            if "1042" in str(resp) and "error code" in str(resp):
                raise ContainerProvisioningError(f"Error 1042 creating workflow: {resp}")
            if attempt < max_create_retries:
                time.sleep(5)
                continue
            self.logging.error(f"Workflow creation failed (status={status_code}): {resp}")
            end = datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.stats.failure = True
            return result

        if instance_id is None:
            self.logging.error("Failed to obtain workflow instance ID")
            end = datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.stats.failure = True
            return result

        # Step 2: poll for completion
        poll_url = f"{self._orchestrator_url}?id={instance_id}"
        poll_interval = 5
        max_poll_time = 7200
        elapsed = 0
        while elapsed < max_poll_time:
            time.sleep(poll_interval)
            elapsed += poll_interval
            try:
                status_code, raw = self._http_get(poll_url)
            except Exception as e:
                self.logging.warning(
                    f"Status poll network error (elapsed={elapsed}s): {e} — retrying"
                )
                continue
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                text = raw.decode()
                self.logging.warning(f"Status poll non-JSON (elapsed={elapsed}s): {text[:100]}")
                continue

            wf_status = resp.get("status")
            if wf_status == "complete":
                end = datetime.now()
                result = ExecutionResult.from_times(begin, end)
                result.output = resp.get("output") or {}
                return result
            if wf_status == "errored":
                end = datetime.now()
                result = ExecutionResult.from_times(begin, end)
                self.logging.error(f"Workflow {self.workflow_name} errored: {resp.get('error')}")
                result.stats.failure = True
                return result
            # Still running (queued/running/paused) — keep polling

        end = datetime.now()
        self.logging.error(
            f"Workflow {self.workflow_name} did not complete within {max_poll_time}s"
        )
        result = ExecutionResult.from_times(begin, end)
        result.stats.failure = True
        return result

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        """Invoke the workflow synchronously: create instance, poll until complete.

        Retries on error 1042 (CPU time limit on cold start) up to 3 times.
        """
        self.logging.debug(f"Invoke workflow {self.workflow_name} at {self._orchestrator_url}")
        max_retries = 3
        retry_wait = 10
        for attempt in range(max_retries + 1):
            try:
                return self._do_invoke(payload)
            except ContainerProvisioningError:
                if attempt < max_retries:
                    self.logging.info(
                        f"Workflow cold start (error 1042), waiting {retry_wait}s "
                        f"before retry (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_wait)
                else:
                    raise
        raise RuntimeError("Unreachable")

    def async_invoke(self, payload: dict):
        """Async invocation is not implemented for workflows."""
        raise NotImplementedError("Async invocation is not implemented for workflows")

    def serialize(self) -> dict:
        """Return a serializable dict for caching."""
        return {
            "type": self.typename(),
            "workflow_name": self.workflow_name,
            "orchestrator_url": self._orchestrator_url,
        }

    @staticmethod
    def deserialize(obj: dict) -> "WorkflowLibraryTrigger":
        """Reconstruct a WorkflowLibraryTrigger from a cached dict."""
        return WorkflowLibraryTrigger(obj["workflow_name"], obj["orchestrator_url"])

import concurrent.futures
import datetime
import uuid
from typing import Optional

import requests

from sebs.faas.function import ExecutionResult, Trigger


class WorkflowSonataFlowTrigger(Trigger):
    def __init__(self, workflow_id: str, base_url: str, endpoint_prefix: str = "services"):
        super().__init__()
        self._workflow_id = workflow_id
        self._base_url = base_url.rstrip("/")
        self._endpoint_prefix = endpoint_prefix.strip("/")

    @staticmethod
    def typename() -> str:
        return "SonataFlow.WorkflowTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def _endpoint(self) -> str:
        if self._endpoint_prefix:
            return f"{self._base_url}/{self._endpoint_prefix}/{self._workflow_id}"
        return f"{self._base_url}/{self._workflow_id}"

    def _candidate_endpoints(self) -> list[tuple[str, str]]:
        """
        Return a list of candidate endpoints to try.

        Kogito/SonataFlow images have historically exposed the workflow start endpoint
        either at `/{workflowId}` or at `/services/{workflowId}` depending on version/config.
        """
        candidates = [self._endpoint_prefix, "", "services"]
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for prefix in candidates:
            prefix = (prefix or "").strip("/")
            if prefix in seen:
                continue
            seen.add(prefix)
            if prefix:
                out.append((prefix, f"{self._base_url}/{prefix}/{self._workflow_id}"))
            else:
                out.append((prefix, f"{self._base_url}/{self._workflow_id}"))
        return out

    def _invoke(self, payload: dict) -> ExecutionResult:
        import time
        request_id = str(uuid.uuid4())[0:8]
        begin = datetime.datetime.now()
        result = ExecutionResult.from_times(begin, begin)
        try:
            body = payload
            if isinstance(payload, dict):
                body = dict(payload)
                body.setdefault("request_id", request_id)
            endpoint_used = self._endpoint()

            # Retry logic for 404 (workflow not loaded yet)
            max_retries = 30
            retry_delay = 2
            resp = None
            original_endpoint = endpoint_used

            for attempt in range(max_retries):
                # Try the main endpoint first
                resp = requests.post(
                    endpoint_used,
                    json=body,
                    timeout=900,
                )
                self.logging.debug(f"Attempt {attempt + 1}: {endpoint_used} returned {resp.status_code}")

                # Check if we should retry
                if resp.status_code == 404:
                    # Auto-detect the correct endpoint layout.
                    found_endpoint = False
                    for prefix, endpoint in self._candidate_endpoints():
                        if endpoint == original_endpoint:
                            # Already tried this one as the main attempt
                            continue
                        self.logging.debug(f"Trying candidate: {endpoint}")
                        resp = requests.post(
                            endpoint,
                            json=body,
                            timeout=900,
                        )
                        self.logging.debug(f"Candidate {endpoint} returned {resp.status_code}")
                        if resp.status_code != 404 and resp.status_code != 503:
                            # Found the correct endpoint!
                            self._endpoint_prefix = prefix
                            endpoint_used = endpoint
                            found_endpoint = True
                            self.logging.info(f"Found workflow at {endpoint}")
                            break

                    if not found_endpoint and attempt < max_retries - 1:
                        # Workflow not loaded yet, wait and retry
                        self.logging.info(
                            f"Workflow endpoint not ready (404), retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_delay)
                        # Reset to original endpoint for next attempt
                        endpoint_used = original_endpoint
                        continue
                    elif not found_endpoint:
                        # Final attempt failed
                        self.logging.error(f"Workflow endpoint not found after {max_retries} attempts")
                        break
                elif resp.status_code in [500, 503] and attempt < max_retries - 1:
                    # Service error (SonataFlow loading/restarting), wait and retry
                    self.logging.info(
                        f"SonataFlow not ready ({resp.status_code}), retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    endpoint_used = original_endpoint
                    continue

                # Success or non-retryable error, break out of retry loop
                break

            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            if resp is not None and resp.status_code >= 300:
                result.stats.failure = True
                try:
                    error_text = resp.text[:500] if len(resp.text) > 500 else resp.text
                except:
                    error_text = "<unable to read response>"
                self.logging.error(
                    f"SonataFlow invocation failed ({resp.status_code}): {error_text}"
                )
            elif resp is not None:
                try:
                    result.output = resp.json()
                except Exception as e:
                    result.stats.failure = True
                    self.logging.error(f"Failed to parse SonataFlow response: {e}")
            else:
                result.stats.failure = True
                self.logging.error("SonataFlow invocation failed: No response received")
        except Exception as exc:
            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            result.stats.failure = True
            self.logging.error(f"SonataFlow invocation error: {exc}")
        return result

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        return self._invoke(payload)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        return pool.submit(self._invoke, payload)

    def serialize(self) -> dict:
        return {
            "type": "SONATAFLOW",
            "workflow_id": self._workflow_id,
            "base_url": self._base_url,
            "endpoint_prefix": self._endpoint_prefix,
        }

    @classmethod
    def deserialize(cls, obj: dict) -> "WorkflowSonataFlowTrigger":
        return cls(obj["workflow_id"], obj["base_url"], obj.get("endpoint_prefix", "services"))

    def update(self, base_url: Optional[str] = None, endpoint_prefix: Optional[str] = None):
        if base_url:
            self._base_url = base_url.rstrip("/")
        if endpoint_prefix is not None:
            self._endpoint_prefix = endpoint_prefix.strip("/")

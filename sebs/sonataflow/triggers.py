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
        request_id = str(uuid.uuid4())[0:8]
        begin = datetime.datetime.now()
        result = ExecutionResult.from_times(begin, begin)
        try:
            endpoint_used = self._endpoint()
            resp = requests.post(
                endpoint_used,
                json={"payload": payload, "request_id": request_id},
                timeout=900,
            )
            if resp.status_code == 404:
                # Auto-detect the correct endpoint layout.
                for prefix, endpoint in self._candidate_endpoints():
                    if endpoint == endpoint_used:
                        continue
                    resp = requests.post(
                        endpoint,
                        json={"payload": payload, "request_id": request_id},
                        timeout=900,
                    )
                    endpoint_used = endpoint
                    if resp.status_code != 404:
                        self._endpoint_prefix = prefix
                        break
            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            if resp.status_code >= 300:
                result.stats.failure = True
                self.logging.error(
                    f"SonataFlow invocation failed ({resp.status_code}): {resp.text}"
                )
            else:
                result.output = resp.json()
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

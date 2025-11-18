import concurrent.futures
import datetime
import uuid
from typing import Optional

from sebs.faas.function import ExecutionResult, Trigger
from sebs.local.executor import LocalWorkflowExecutor, WorkflowExecutionError


class WorkflowLocalTrigger(Trigger):
    def __init__(self, definition_path: str, bindings: dict):
        super().__init__()
        self._definition_path = definition_path
        self._bindings = bindings
        self._executor = LocalWorkflowExecutor(definition_path, bindings)

    @staticmethod
    def typename() -> str:
        return "Local.WorkflowLocalTrigger"

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.HTTP

    def _invoke(self, payload: dict) -> ExecutionResult:
        request_id = str(uuid.uuid4())[0:8]
        begin = datetime.datetime.now()
        result = ExecutionResult.from_times(begin, begin)
        try:
            output = self._executor.run(payload, request_id)
            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            result.output = output
        except WorkflowExecutionError as exc:
            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            result.stats.failure = True
            self.logging.error(f"Workflow execution failed: {exc}")
        except Exception as exc:
            end = datetime.datetime.now()
            result = ExecutionResult.from_times(begin, end)
            result.request_id = request_id
            result.stats.failure = True
            self.logging.error(f"Workflow execution error: {exc}")
        return result

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        return self._invoke(payload)

    def async_invoke(self, payload: dict) -> concurrent.futures.Future:
        pool = concurrent.futures.ThreadPoolExecutor()
        return pool.submit(self._invoke, payload)

    def serialize(self) -> dict:
        return {
            "type": "LOCAL",
            "definition_path": self._definition_path,
            "bindings": self._bindings,
        }

    @classmethod
    def deserialize(cls, obj: dict) -> "WorkflowLocalTrigger":
        return cls(obj["definition_path"], obj["bindings"])

    def update(self, definition_path: str, bindings: dict):
        self._definition_path = definition_path
        self._bindings = bindings
        self._executor = LocalWorkflowExecutor(definition_path, bindings)

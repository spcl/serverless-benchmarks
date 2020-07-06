from sebs.faas.function import Function, ExecutionResult


class OpenWhiskFunction(Function):
    def sync_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def async_invoke(self, payload: dict) -> ExecutionResult:
        pass

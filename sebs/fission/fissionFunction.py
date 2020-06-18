from sebs.faas.function import Function
import subprocess


class FissionFunction(Function):
    def __init__(self, name: str):
        super().__init__(name)

    def sync_invoke(self, payload: dict):
        subprocess.run(
            f'fission fn test --name {self.name}'.split(), check=True
        )

    def async_invoke(self, payload: dict):
        raise Exception("Non-trigger invoke not supported!")

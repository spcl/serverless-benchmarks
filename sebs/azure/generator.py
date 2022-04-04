from sebs.faas.generator import *


class AzureGenerator(Generator):

    def __init__(self):
        def _export(payload: dict):
            return payload["src"]

        super().__init__(_export)

    def postprocess(self, states: List[State], payloads: List[dict]) -> dict:
        code = ("import azure.durable_functions as df\n\n"
                "def run_workflow(context: df.DurableOrchestrationContext):\n"
                "\tres = context.get_input()")

        for payload in payloads:
            src = payload["src"].splitlines()
            src = "\n\t".join(src)
            code += "\n\t" + src

        code += ("\n\treturn res"
                 "\n\nmain = df.Orchestrator.create(run_workflow)")

        return {
            "src": code
        }

    def encode_task(self, state: Task) -> dict:
        code = (f"res = yield context.call_activity(\"{state.func_name}\", res)\n")

        return {
            "src": code
        }
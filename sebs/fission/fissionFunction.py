# from sebs.faas.function import Function, ExecutionResult
# import json
# import datetime
# import requests
# import logging
#
#
# class FissionFunction(Function):
#     def __init__(self, name: str):
#         super().__init__(name)
#
#     def sync_invoke(self, payload: dict):
#         url = "http://localhost:5051/benchmark"
#         readyPayload = json.dumps(payload)
#         headers = {"content-type": "application/json"}
#         begin = datetime.datetime.now()
#         logging.info(f"Function {self.name} invoking...")
#         response = requests.request("POST", url, data=readyPayload, headers=headers)
#         end = datetime.datetime.now()
#         logging.info(f"Function {self.name} returned response with code: {response.status_code}")
#         fissionResult = ExecutionResult(begin, end)
#         if response.status_code != 200:
#             logging.error("Invocation of {} failed!".format(self.name))
#             logging.error("Input: {}".format(readyPayload))
#
#             # TODO: this part is form AWS, need to be rethink
#             # self._deployment.get_invocation_error(
#             #     function_name=self.name,
#             #     start_time=int(begin.strftime("%s")) - 1,
#             #     end_time=int(end.strftime("%s")) + 1,
#             # )
#
#             fissionResult.stats.failure = True
#             return fissionResult
#         returnContent = json.loads(json.loads(response.content))
#         fissionResult.parse_benchmark_output(returnContent)
#         return fissionResult
#
#     def async_invoke(self, payload: dict):
#         raise Exception("Non-trigger invoke not supported!")

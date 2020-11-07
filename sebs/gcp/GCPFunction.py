from ..faas.function import Function
import json
import datetime
import logging
import time


class GCPFunction(Function):
    @property
    def code_package(self):
        return self._code_package

    def __init__(self, name: str, code_package: str, deployment):
        super().__init__(name)
        self._code_package = code_package
        self._deployment = deployment

    def sync_invoke(self, payload: dict):
        config = self._deployment.config
        full_func_name = "projects/{project_name}/locations/{location}/functions/{func_name}".format(
            project_name=config.project_name,
            location=config.region,
            func_name=self.name,
        )
        print(payload)
        payload = json.dumps(payload)
        print(payload)
        function_client = self._deployment.get_function_client()
        status_req = (
            function_client.projects().locations().functions().get(name=full_func_name)
        )

        deployed = False
        while not deployed:
            status_res = status_req.execute()
            if status_res["status"] == "ACTIVE":
                deployed = True
            else:
                time.sleep(5)

        req = (
            function_client.projects()
            .locations()
            .functions()
            .call(name=full_func_name, body={"data": payload})
        )
        begin = datetime.datetime.now()
        res = req.execute()
        end = datetime.datetime.now()

        print("RES: ", res)

        if "error" in res.keys() and res["error"] != "":
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(payload))
            raise RuntimeError()

        print("Result", res["result"])
        return {
            "return": res["result"],
            "client_time": (end - begin) / datetime.timedelta(microseconds=1),
        }

    def async_invoke(self, payload: dict):
        # TO DO (?)
        pass

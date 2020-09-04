import subprocess

from sebs.faas.function import Function, ExecutionResult
import json
import datetime
import logging
import re
from typing import List


class OpenwhiskFunction(Function):
    def __init__(self, name: str, namespace: str = "_"):
        super().__init__(name)
        self.namespace = namespace

    def __add_params__(self, command: List[str], payload: dict) -> List[str]:
        for key, value in payload.items():
            command.append("--param")
            command.append(key)
            command.append(str(value))
        return command

    def sync_invoke(self, payload: dict):
        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        command = self.__add_params__(f"wsk -i action invoke --result {self.name}".split(), payload)
        error = None
        try:
            begin = datetime.datetime.now()
            response = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            end = datetime.datetime.now()
            response = response.stdout.decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            end = datetime.datetime.now()
            logging.error(f"Cannot synchronously invoke action {self.name}, reason: {e}")
            error = e

        openwhiskResult = ExecutionResult(begin, end)
        if error is not None:
            logging.error("Invocation of {} failed!".format(self.name))
            openwhiskResult.stats.failure = True
            return openwhiskResult

        returnContent = json.loads(response)
        logging.info(f"{returnContent}")

        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

    def async_invoke(self, payload: dict):
        import time
        import datetime
        logging.info(f"Function {self.name} of namespace {self.namespace} invoking...")
        command = self.__add_params__(f"wsk -i action invoke --result {self.name}".split(), payload)
        error = None
        try:
            begin = datetime.datetime.now()
            response = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            end = datetime.datetime.now()
            response = response.stdout.decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            end = datetime.datetime.now()
            logging.error(f"Cannot asynchronously invoke action {self.name}, reason: {e}")
            error = e
        openwhiskResult = ExecutionResult(begin, end)
        if error is not None:
            logging.error(f"Invocation of {self.name} failed!")
            openwhiskResult.stats.failure = True
            return openwhiskResult
        id_pattern = re.compile(r"with id ([a-zA-Z0-9]+)$")
        id_match = id_pattern.search(response).group(1)
        if id_match is None:
            logging.error("Cannot parse activation id")
            openwhiskResult.stats.failure = True
            return openwhiskResult
        attempt = 1
        while True:
            logging.info(f"Function {self.name} of namespace getting result. Attempt: {attempt}")
            command = f"wsk -i activation result {id_match}"
            try:
                response = subprocess.run(
                    command.split(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                response = response.stdout.decode("utf-8")
                end = datetime.datetime.now()
                error = None
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.info("No result yet, proceeding...")
                time.sleep(0.05)
                attempt += 1
                error = e
                continue
            break
        if error is not None:
            logging.error(f"Function {self.name} with id {id_match} finished unsuccessfully")
            openwhiskResult.stats.failure = True
            return openwhiskResult

        logging.info(f"Function {self.name} with id {id_match} finished successfully")

        returnContent = json.loads(response)
        openwhiskResult = ExecutionResult(begin, end)
        openwhiskResult.parse_benchmark_output(returnContent)
        return openwhiskResult

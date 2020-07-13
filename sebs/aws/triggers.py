import base64
import datetime
import json
import logging
import time
from typing import Dict, Optional  # noqa


from sebs.aws.aws import AWS
from sebs.faas.function import ExecutionResult, Trigger


class LibraryTrigger(Trigger):
    def __init__(self, fname: str, deployment_client: Optional[AWS] = None):
        self.name = fname
        self._deployment_client = deployment_client

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.LIBRARY

    def sync_invoke(self, payload: dict) -> ExecutionResult:

        logging.info(f"AWS: Invoke function {self.name}")

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        begin = datetime.datetime.now()
        ret = client.invoke(
            FunctionName=self.name, Payload=serialized_payload, LogType="Tail"
        )
        end = datetime.datetime.now()

        aws_result = ExecutionResult(begin, end)
        if ret["StatusCode"] != 200:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        if "FunctionError" in ret:
            logging.error("Invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            self.deployment_client.get_invocation_error(
                function_name=self.name,
                start_time=int(begin.strftime("%s")) - 1,
                end_time=int(end.strftime("%s")) + 1,
            )
            aws_result.stats.failure = True
            return aws_result
        logging.info(f"AWS: Invoke of function {self.name} was successful")
        log = base64.b64decode(ret["LogResult"])
        function_output = json.loads(ret["Payload"].read().decode("utf-8"))

        # AWS-specific parsing
        AWS.parse_aws_report(log.decode("utf-8"), aws_result)
        # General benchmark output parsing
        # For some reason, the body is dict for NodeJS but a serialized JSON for Python
        if isinstance(function_output["body"], dict):
            aws_result.parse_benchmark_output(function_output["body"])
        else:
            aws_result.parse_benchmark_output(json.loads(function_output["body"]))
        return aws_result

    def async_invoke(self, payload: dict):

        serialized_payload = json.dumps(payload).encode("utf-8")
        client = self.deployment_client.get_lambda_client()
        ret = client.invoke(
            FunctionName=self.name,
            InvocationType="Event",
            Payload=serialized_payload,
            LogType="Tail",
        )
        if ret["StatusCode"] != 202:
            logging.error("Async invocation of {} failed!".format(self.name))
            logging.error("Input: {}".format(serialized_payload.decode("utf-8")))
            raise RuntimeError()
        return ret

    def serialize(self) -> dict:
        return {"type": "Library", "name": self.name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return LibraryTrigger(obj["name"])



class StorageTrigger(Trigger):
    def __init__(self, function_arn: str, bucket_name: str, deployment_client: Optional[AWS] = None):
        self.function_arn = function_arn
        self.bucket_name = bucket_name
        self._deployment_client = deployment_client

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.STORAGE

    def create(self):
        self.bucket_name = self._deployment_client.storage.create_bucket(self.bucket_name)
        s3_client = self._deployment_client.storage.client
        TriggerUtils.add_function_permission(self._deployment_client.get_lambda_client(), "1", self.function_arn, 's3.amazonaws.com')
        s3_client.put_bucket_notification_configuration(
            Bucket=self.bucket_name,
            NotificationConfiguration={'LambdaFunctionConfigurations': [
                {'LambdaFunctionArn': self.function_arn, 'Events': ['s3:ObjectCreated:*']}]})

    def delete(self):
        s3_client = self._deployment_client.storage.client
        TriggerUtils.add_function_permission(self._deployment_client.get_lambda_client(), "2", self.function_arn, 's3.amazonaws.com')
        s3_client.put_bucket_notification_configuration(
            Bucket=self.bucket_name, NotificationConfiguration={})

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def async_invoke(self, payload: dict):
        file_path = payload['file_path']
        key = payload['key']
        self._deployment_client.get_storage().upload(self.bucket_name, file_path, key)

    def serialize(self) -> dict:
        return {"type": "Storage", "arn": self.function_arn, "bucket": self.bucket_name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return StorageTrigger(obj["arn"], obj["bucket"])

class TimerTrigger(Trigger):
    def __init__(self, function_name: str, function_arn: str, schedule_pattern: str, deployment_client: Optional[AWS] = None, unique_rule_name: str = None):
        self.function_name = function_name
        self.function_arn = function_arn
        self.schedule_pattern = schedule_pattern
        self._deployment_client = deployment_client
        self.unique_rule_name = unique_rule_name

    @property
    def deployment_client(self) -> AWS:
        assert self._deployment_client
        return self._deployment_client

    @deployment_client.setter
    def deployment_client(self, deployment_client: AWS):
        self._deployment_client = deployment_client

    @staticmethod
    def trigger_type() -> Trigger.TriggerType:
        return Trigger.TriggerType.TIMER

    def create(self):
        if self.unique_rule_name is not None:
            base_name = self.unique_rule_name if self.unique_rule_name is not None else ''.join(filter(str.isalnum, self.function_name))
        self.unique_rule_name = '{}{}'.format(base_name, time.time())
        events_client = self._deployment_client.get_events_client()
        events_client.put_rule(
            Name=self.unique_rule_name,
            ScheduleExpression=self.schedule_pattern
        )
        TriggerUtils.add_function_permission(self._deployment_client.get_lambda_client(), "1", self.function_arn, 'events.amazonaws.com')
        events_client.put_targets(
            Rule=self.unique_rule_name,
            Targets=[
                {
                    "Id": "1",
                    "Arn": self.function_arn
                }
            ]
        )

    def delete(self):
        events_client = self._deployment_client.get_events_client()
        TriggerUtils.add_function_permission(self._deployment_client.get_lambda_client(), "2", self.function_arn, 'events.amazonaws.com')
        events_client.remove_targets(Rule=self.unique_rule_name, Ids=["1"])
        events_client.delete_rule(Name=self.unique_rule_name)

    def sync_invoke(self, payload: dict) -> ExecutionResult:
        pass

    def async_invoke(self, payload: dict):
        pass

    def serialize(self) -> dict:
        return {"type": "Timer", "ruleName": self.unique_rule_name}

    @staticmethod
    def deserialize(obj: dict) -> Trigger:
        return TimerTrigger(None, None, None, None, obj["ruleName"])

class TriggerUtils:
    @staticmethod
    def add_function_permission(lambda_client, statement_id, function_arn, principal):
        try:
            lambda_client.add_permission(
                FunctionName=function_arn,
                StatementId=statement_id,
                Action='lambda:InvokeFunction',
                Principal=principal,
            )
        except:
            pass #occurs only if function already exists
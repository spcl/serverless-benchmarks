import boto3
import json
from time import sleep

# it's only for tests, i will delete this branch

# Credentials
ACCESS_KEY = ''
SECRET_KEY = ''
SESSION_TOKEN = ''
REGION_NAME = ''

client = boto3.client(
    'stepfunctions',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    aws_session_token=SESSION_TOKEN,
    region_name=REGION_NAME
)

sample_definition = {
    "Comment": "Simple step pipeline for test",
    "StartAt": "state_1",
    "States": {
        "state_1": {
            "Resource": "arn:aws:lambda:us-east-1:427909965706:function:mati_lambda",
            "Type": "Task",
            "Next": "state_2"
        },
        "state_2": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:427909965706:function:mati_lambda",
            "Next": "End"
        },
        "End": {
            "Type": "Succeed"
        }
    }
}


def get_state_machines():
    response = client.list_state_machines()
    if response.get('stateMachines') is None:
        return None
    return response.get('stateMachines')


def get_state_machine_arn(name):
    response = client.list_state_machines()
    for state_machine in response.get('stateMachines'):
        if state_machine['name'] == name:
            return state_machine['stateMachineArn']
    return None


def execute_state_machine(name, input):
    state_machine_arn = get_state_machine_arn(name)
    try:
        execution_response = client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(input)
        )
    except Exception as ex:
        print('error: execute state machine - ', ex)
        return False

    execution_arn = execution_response.get('executionArn')
    return execution_arn


def create_state_machine(name, definition, role_arn):
    try:
        response = client.create_state_machine(
            name=name,
            definition=json.dumps(definition),
            roleArn=role_arn
        )
    except Exception as ex:
        print('error: create state machine - ', ex)
        return False
    return True


def get_execution_history(execution_arr):
    try:
        response = client.get_execution_history(
            executionArn=execution_arr,
            maxResults=1000,
            reverseOrder=False
        )
    except Exception as ex:
        print('error: get execution history - ', ex)
        return None
    return response


ROLE = 'arn:aws:iam::427909965706:role/manual_created_role_1'

# new_state_machine = create_state_machine('via-python', sample_definition, ROLE)
execution_arr = execute_state_machine('via-python', None)
history = get_execution_history(execution_arr)

print(history)
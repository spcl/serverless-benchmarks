import boto3
import json
import time
# it's only for tests

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

iam_client = boto3.client(
    'iam',
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


# We can use AWSLambdaRole policy instead of creating a new one (if lambda:InvokeFunction is enough for us)
# AWS_LAMBDA_ROLE_ARN = 'arn:aws:iam::aws:policy/service-role/AWSLambdaRole'
def iam_create_policy():
    benchmarks_policy_definition = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:InvokeFunction"
                ],
                "Resource": [
                    "*"
                ]
            }
        ]
    }

    try:
        response = iam_client.create_policy(
            PolicyName='ServerlessBenchmarksPolicy',
            Description='Allows benchmark lambdas to access AWS',
            PolicyDocument=json.dumps(benchmarks_policy_definition)
        )
    except Exception as ex:
        print('error: create policy - ', ex)
        return None

    return response['Policy']['Arn']


def iam_create_role():
    assume_role_policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com",
                "Service": "states.amazonaws.com"
            },
            "Action": ["sts:AssumeRole"]
        }]
    }

    try:
        response = iam_client.create_role(
            RoleName='ServerlessBenchmarksRole',
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description='Role for serverless benchmarks',
        )
    except Exception as ex:
        print('error: create role - ', ex)
        return None
    return response['Role']['Arn']


def iam_attach_policy_to_role(role_name, policy_arn):
    try:
        response = iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_arn
        )
    except Exception as ex:
        print('error: attach policy - ', ex)
        return None
    return response

# list state machines
# print(get_state_machines())

# create role with policy
role_arn = iam_create_role()
policy = iam_create_policy()
iam_attach_policy_to_role('ServerlessBenchmarksRole', policy)

# create state machine
BENCHMARK_NAME = 'sm-created-via-python-9'
create_state_machine(BENCHMARK_NAME, sample_definition, role_arn)

# execute created state machine
time.sleep(10.0) # it need some time (about 6-10s. in this example) - otherwise execution will fail
execution_arr = execute_state_machine(BENCHMARK_NAME, None)

# get execution history
history = get_execution_history(execution_arr)
print(history)

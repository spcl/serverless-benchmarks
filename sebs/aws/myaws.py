import boto3
import json
import time


# Credentials
ACCESS_KEY = 'AKIA3YFCLKIJM43KK5WB'
SECRET_KEY = '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'
SESSION_TOKEN =''
REGION_NAME = 'us-east-1'

ROLE_NAME='ServerlessBenchmarksRole'
POLICY_NAME='ServerlessBenchmarksPolicy'
BENCHMARK_NAME = 'sm-created-via-python-9'

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
            "Resource": "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd",
            "Type": "Task",
            "Next": "End"
       },
        "End": {
            "Type": "Succeed"
        }
    }
}

role_policy = {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com",
                "Service": "states.amazonaws.com"
            },
            "Action": ["sts:AssumeRole"]
        }]
}

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
            },
            {
                "Effect": "Allow",
                "Action": [
                    "states:ListStateMachines",
                    "states:ListActivities",
                    "states:CreateStateMachine",
                    "states:CreateActivity"
                ],
                "Resource": [ 
                    "*" 
                ]
            }
        ]
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


def iam_create_policy(policy_name):
    try:
        response = iam_client.create_policy(
            PolicyName=policy_name,
            Description='Allows benchmark lambdas to access AWS',
            PolicyDocument=json.dumps(benchmarks_policy_definition)
        )
    except Exception as ex:
        print('error: create policy - ', ex)
        return None

    return response['Policy']['Arn']


def iam_delete_policy(policy_arn):
    try:
        response = iam_client.delete_policy(
            PolicyArn=policy_arn,
        )
    except Exception as ex:
        print('error: delete policy - ', ex)
        return None

    return response


def iam_create_role(role_name):
    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(role_policy),
            Description='Role for serverless benchmarks',
        )
       
    except Exception as ex:
        print('error: create role - ', ex)
        return None
    return response['Role']['Arn']


def iam_delete_role(role_name):
    try:
        response = iam_client.delete_role(
            RoleName=role_name,
        )
       
    except Exception as ex:
        print('error: delete role - ', ex)
        return None
    return response


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


def iam_detach_policy_from_role(role_name, policy_arn):
    try:
        response = iam_client.detach_role_policy(
            PolicyArn=policy_arn,
            RoleName=role_name
        )
    except Exception as ex:
        print('error: detach policy - ', ex)
        return None
    return response

# ------------------------------------------------------------------------------------

# create role, policy. attach policy to the role
role_arn = iam_create_role(ROLE_NAME)
policy_arn = iam_create_policy(POLICY_NAME)
iam_attach_policy_to_role(ROLE_NAME, policy_arn)

try:
    # create state machine
    create_state_machine(BENCHMARK_NAME, sample_definition, role_arn)

    # list state machines
    print(get_state_machines())

    # execute created state machine
    time.sleep(10.0) # it need some time (about 6-10s. in this example) - otherwise execution will fail
    execution_arr = execute_state_machine(BENCHMARK_NAME, None)

    # get execution history
    history = get_execution_history(execution_arr)
    print(history)

except Exception as ex:
    print('Error while running benchmark', ex)

finally:
    # CLEANUP
    iam_detach_policy_from_role(ROLE_NAME, policy_arn)
    iam_delete_role(ROLE_NAME)
    iam_delete_policy(policy_arn)
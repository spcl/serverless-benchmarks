import json


class State(object):
    def __init__(self, name: str, lambda_arn: str = "", state_type: str = "", next_step: str = ""):
        """
        :param name: single step symbolic name
        :param lambda_arn: arn of lamba function to be executed withing step
        :param state_type: step's type
        :param next_step: next step to be executed after he current one
        """
        self._name = name
        self._resource = lambda_arn
        self._type = state_type
        self._next = next_step

    def state_as_map(self):
        data = {'Type': self._type}

        if self._resource:
            data['Resource'] = self._resource

        if self._next:
            data['Next'] = self._next
        return data


class StepMachine:
    def __init__(self, name: str, states: [State], startAt: str = "", comment: str = ""):
        """
        :param name: step machine symbolic name
        :param states: state array
        :param startAt: starting state name
        :param comment: optional comment
        """
        if len(name.strip()) < 2:
            raise Exception("Step machine name should have at least two characters.")
        self._name = name
        self._states = states
        self._startAt = startAt
        self._comment = comment
        self.state_machine_arn = None

    def get_as_aws_json(self):
        """
        Convert object to json

        :return: json-aws state machine definition
        """
        data = {}

        if self._comment:
            data['Comment'] = self._comment

        if not self._startAt:
            raise Exception("The starting point is not defined.")
        data['StartAt'] = self._startAt

        if not self._states:
            raise Exception("There are no defined states.")
        data['States'] = self.__states_as_map()

        return json.dumps(data)

    def __states_as_map(self):
        """
        Change all of the states into json objects

        :return: map of states in json format
        """
        states = {}
        for state in self._states:
            states[state._name] = state.state_as_map()
        return states

    def execute(self, client, role_arn: str, state_input: str = None):
        """
        Execute the state machine within the current class

        :param client: boto3.client object
        :param role_arn: arn of the role
        :param state_input: optional input
        :return: execution arn
        """
        if not self.state_machine_arn:
            self.state_machine_arn = self.__create(client, role_arn)
        try:
            execution_response = client.start_execution(
                stateMachineArn=self.state_machine_arn,
                input=json.dumps(state_input)
            )
        except Exception as ex:
            print('error during execution - ', ex)
            return False

        execution_arn = execution_response.get('executionArn')
        return execution_arn

    def __create(self, client, role_arn):
        """
        Create the state machine, requires object state

        :param client: boto3 client object
        :param role_arn: arn of the role
        :return: arn of the created state machine
        """
        try:
            response = client.create_state_machine(
                name=self._name,
                definition=self.get_as_aws_json(),
                roleArn=role_arn
            )
            self.state_machine_arn = response['stateMachineArn']
        except Exception as ex:
            print('error: state machine not created - ', ex)
            return ''
        return response['stateMachineArn']

    def delete(self, client, sm_arn: str = None):
        """
        Delete local step machine, if no arn is specified

        :param client: boto3 client object
        :param sm_arn: optional state machine arn, if not specified - object's sm is deleted
        :return:
        """
        arn = sm_arn
        if not arn:
            if not self.state_machine_arn:
                raise Exception("Argument arn is empty and object has no created state machine")
            arn = self.state_machine_arn

        try:
            response = client.delete_state_machine(
                stateMachineArn=arn
            )
            return response
        except Exception as ex:
            print('error: state machine was not deleted - ', ex)


# Example of state json creation, delete for production
state1: State = State("state_1",
                      "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd",
                      "Task",
                      "End"
                      )
state2: State = State("End", state_type="Succeed")
sample_machine: StepMachine = StepMachine(name="test", comment="Simple step pipeline for test",
                                          startAt="state_1",
                                          states=[state1, state2])

print(sample_machine.get_as_aws_json())

# End of example

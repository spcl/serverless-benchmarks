import json
from abc import ABC, abstractmethod


class State(ABC):
    def __init__(self, state_name: str, state_type: str):
        """
        Abstract class to describe the base for Steps.

        :param state_name: step's symbolic name.
        :param state_type: step's type.
        """
        self._name: str = state_name
        self._type: str = state_type

    @abstractmethod
    def state_as_map(self) -> {}:
        """
        Return object as a map.

        :return: dictionary containing aws-relevant json properties.
        """
        data = {"Type": self._type}
        return data


class StateMachine:
    def __init__(self, states: [State], startAt: str):
        """
        State machine definition.

        :param states: array of states.
        :param startAt: name of the starting state.
        """

        if not states:
            raise Exception("You should provide at least one state in the argument array.")
        self._states = states

        if not startAt:
            raise Exception("You should provide a starting step as argument.")
        self._startAt = startAt

    def get_as_map(self) -> {}:
        """
        Return object as a map.

        :return: dictionary containing aws-relevant json properties.
        """
        data = {}

        data["StartAt"] = self._startAt
        data["States"] = self.__states_as_map()

        return data

    def __states_as_map(self) -> {}:
        """
        Convert all of the states into maps.

        :return: map of states.
        """
        states = {}

        for state in self._states:
            states[state._name] = state.state_as_map()
        return states


class ParallelState(State):
    def __init__(self, state_name: str, branches: [StateMachine], next_step: str):
        """
        Responsible for parallel execution of its branches.

        :param branches: array of branches to be executed in parallel
        :param next_step: next step to be executed after all the branches finish
        """
        super().__init__(state_name, "Parallel")
        if not next_step:
            raise Exception("You should provide a valid next step as argument.")
        self._next = next_step

        if len(branches) < 1:
            raise Exception("You should provide at least one branch to the parallel task.")
        self._branches = branches

    def state_as_map(self) -> {}:
        data = super().state_as_map()
        data["Next"] = self._next

        mapped_branches = []
        for branch in self._branches:
            mapped_branches.append(branch.get_as_map())

        data["Branches"] = mapped_branches

        return data


class WaitState(State):
    def __init__(self, state_name: str, next_state: str, seconds: int):
        """
        State used for waiting.

        :param next_state: step to be executed after this one.
        :param seconds: time in seconds to be spent waiting in this step.
        """
        super().__init__(state_name, "Wait")

        if not next_state:
            raise Exception("You should provide a valid next step as argument.")
        self._next = next_state

        if seconds < 0:
            raise Exception("Wait time cannot be less than 0 seconds")
        self._seconds = seconds

    def state_as_map(self) -> {}:
        data = super().state_as_map()
        data["Next"] = self._next
        data["Seconds"] = self._seconds
        return data


class SucceedState(State):
    def __init__(self, state_name: str):
        """
        Terminal state.
        """
        super().__init__(state_name, "Succeed")

    def state_as_map(self) -> {}:
        return super().state_as_map()


class FailState(State):
    def __init__(self, state_name: str, error: str, cause: str):
        """
        Terminal state that fails current scope.

        :param error: error name.
        :param cause: human-readable message.
        """
        super().__init__(state_name, "Fail")
        self._error = error
        self._cause = cause

    def state_as_map(self) -> {}:
        data = super().state_as_map()
        data["Error"] = self._error
        data["Cause"] = self._cause
        return data


class TaskState(State):
    def __init__(
        self,
        state_name: str,
        lambda_arn: str,
        next_step: str = "",
        timeout: int = 60,
        is_end_state: bool = False,
    ):
        """
        Task state class.

        :param timeout: if the step runs longer than timeout - state fails with States.Timeout.
        :param lambda_arn: arn of lambda function to be executed withing step.
        :param next_step: next step to be executed after he current one.
        :param is_end_state: if set to True, this is a terminal state.
        """
        super().__init__(state_name, "Task")
        self._resource: str = lambda_arn
        self._next: str = next_step
        self._end: bool = is_end_state

        if timeout <= 0:
            raise Exception("Timeout value should be a positive value.")
        self._timeout = timeout

    def state_as_map(self) -> {}:
        data = super().state_as_map()

        data["Resource"] = self._resource

        if self._next:
            data["Next"] = self._next
        elif self._end:
            data["End"] = self._end
        else:
            raise Exception("No next step has been specified, nor this is a terminal state.")

        data["TimeoutSeconds"] = self._timeout

        return data


class StepMachine(StateMachine):
    def __init__(self, name: str, states: [State], startAt: str, comment: str = ""):
        """
        :param name: step machine symbolic name.
        :param comment: optional comment.
        """
        super().__init__(states, startAt)

        if len(name.strip()) < 2:
            raise Exception("Step machine name should have at least two characters.")
        self._name = name

        self._comment = comment
        self.state_machine_arn = None

    def get_as_map(self) -> {}:
        data = super().get_as_map()

        if self._comment:
            data["Comment"] = self._comment

        return data

    def get_as_aws_json(self) -> str:
        """
        Convert object to json string.

        :return: json-aws state machine definition.
        """

        return json.dumps(self.get_as_map())

    def execute(self, client, role_arn: str, state_input: str = None) -> str:
        """
        Execute the state machine within the current class.

        :param client: boto3.client object.
        :param role_arn: arn of the role.
        :param state_input: optional input.
        :return: execution arn.
        """
        if not self.state_machine_arn:
            self.state_machine_arn = self.__create(client, role_arn)
        try:
            execution_response = client.start_execution(
                stateMachineArn=self.state_machine_arn, input=json.dumps(state_input)
            )
        except Exception as ex:
            print("error during execution - ", ex)
            return ""

        execution_arn = execution_response.get("executionArn")
        return execution_arn

    def __create(self, client, role_arn) -> str:
        """
        Create the state machine, requires object state.

        :param client: boto3.client object.
        :param role_arn: arn of the role.
        :return: arn of the created state machine.
        """
        try:
            response = client.create_state_machine(
                name=self._name, definition=self.get_as_map(), roleArn=role_arn
            )
            self.state_machine_arn = response["stateMachineArn"]
        except Exception as ex:
            print("error: state machine not created - ", ex)
            return ""
        return response["stateMachineArn"]

    def delete(self, client, sm_arn: str = None) -> str:
        """
        Delete local step machine, if no arn is specified.

        :param client: boto3.client object.
        :param sm_arn: optional state machine arn, if not specified - objects sm is deleted.
        :return:
        """
        arn = sm_arn
        if not arn:
            if not self.state_machine_arn:
                raise Exception("Argument arn is empty and object has no created state machine.")
            arn = self.state_machine_arn

        try:
            response = client.delete_state_machine(stateMachineArn=arn)
            return response
        except Exception as ex:
            print("error: state machine was not deleted - ", ex)


# Example of state json creation, delete for production
starting_state: TaskState = TaskState(
    "state_1", "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd", "LookupCustomerInfo"
)

first_branch_state1 = TaskState(
    "LookupAddress", "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd", is_end_state=True
)

second_branch_state1 = TaskState(
    "LookupPhone",
    "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd",
    next_step="LookupPhone2",
)

second_branch_state2 = TaskState(
    "LookupPhone2", "arn:aws:lambda:us-east-1:807794332178:function:ex_lmbd", is_end_state=True
)

first_branch: StateMachine = StateMachine([first_branch_state1], "LookupAddress")
second_branch: StateMachine = StateMachine([second_branch_state1], "LookupPhone")

parallel_state: ParallelState = ParallelState(
    "LookupCustomerInfo", [first_branch, second_branch], "NextState"
)

wait_state: WaitState = WaitState("NextState", "Last", 5)

fail_finish_state: FailState = FailState("Last", "TestException", "Human-readeable")

sample_machine: StepMachine = StepMachine(
    name="test",
    comment="Simple step pipeline for test",
    startAt="state_1",
    states=[starting_state, parallel_state, wait_state, fail_finish_state],
)

print(sample_machine.get_as_aws_json())

# End of example

import unittest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from typing import List

# Import system classes
from sebs.aws.aws import AWS
from sebs.azure.azure import Azure
from sebs.gcp.gcp import GCP

# Import config classes for type hinting and setup
from sebs.aws.config import AWSConfig, AWSCredentials, AWSResources
from sebs.azure.config import AzureConfig, AzureCredentials, AzureResources as AzureResourcesConfig # Renamed to avoid conflict
from sebs.gcp.config import GCPConfig, GCPCredentials, GCPResources

# Import specific exceptions for testing
# AWS
from botocore.exceptions import ClientError

# Azure
from azure.core.exceptions import HttpResponseError
from azure.monitor.query import LogsQueryStatus

# GCP
from google.api_core import exceptions as google_exceptions

# Common utilities
from sebs.utils import LoggingHandlers
import logging # For capturing log messages during tests

# Mocks for datetime and time, as they are used in log generation/querying
from datetime import datetime, timedelta, timezone

TEST_FUNCTION_NAME = "test-function"
TEST_INVOCATION_ID = "test-invocation-id-12345"
SAMPLE_LOG_MESSAGES = [
    f"2023-01-01T12:00:00Z START RequestId: {TEST_INVOCATION_ID} Version: $LATEST",
    f"2023-01-01T12:00:01Z {TEST_INVOCATION_ID} INFO: Doing something important.",
    f"2023-01-01T12:00:02Z END RequestId: {TEST_INVOCATION_ID}",
    f"2023-01-01T12:00:03Z REPORT RequestId: {TEST_INVOCATION_ID} Duration: 1000 ms Billed Duration: 1000 ms Memory Size: 128 MB Max Memory Used: 50 MB",
]

class TestAWSLogs(unittest.TestCase):
    def setUp(self):
        self.aws_system = AWS(
            sebs_config=Mock(),
            config=Mock(spec=AWSConfig),
            cache_client=Mock(),
            docker_client=Mock(),
            logger_handlers=LoggingHandlers(logging.DEBUG) # Use actual LoggingHandlers
        )
        # Mock configurations needed by get_invocation_logs
        self.aws_system.config.region = "us-east-1"
        self.aws_system.config.credentials = Mock(spec=AWSCredentials)
        self.aws_system.config.credentials.access_key = "test_access_key"
        self.aws_system.config.credentials.secret_key = "test_secret_key"

        # Mock the logs_client specifically for AWS
        self.mock_boto_client = MagicMock()
        # self.aws_system.logs_client will be set by the method if None,
        # so we patch boto3.client which is called internally.
        self.boto_patcher = patch('boto3.client', return_value=self.mock_boto_client)
        self.boto_patcher.start()

        # Mock time.time used in AWS log retrieval logic
        self.time_patcher = patch('time.time', return_value=1672574400.0) # 2023-01-01T12:00:00Z
        self.mock_time = self.time_patcher.start()

    def tearDown(self):
        self.boto_patcher.stop()
        self.time_patcher.stop()

    def test_get_logs_success_aws(self):
        # Mock paginator and its paginate method
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "events": [
                    {"message": SAMPLE_LOG_MESSAGES[0]},
                    {"message": SAMPLE_LOG_MESSAGES[1]},
                ]
            },
            {
                "events": [
                    {"message": SAMPLE_LOG_MESSAGES[2]},
                    {"message": SAMPLE_LOG_MESSAGES[3]},
                ]
            },
        ]
        self.mock_boto_client.get_paginator.return_value = mock_paginator

        logs = self.aws_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
        self.assertEqual(logs, SAMPLE_LOG_MESSAGES)
        self.mock_boto_client.get_paginator.assert_called_once_with("filter_log_events")
        mock_paginator.paginate.assert_called_once()

        # Check some args of paginate
        args, kwargs = mock_paginator.paginate.call_args
        self.assertEqual(kwargs.get('logGroupName'), f"/aws/lambda/{TEST_FUNCTION_NAME}")
        self.assertEqual(kwargs.get('filterPattern'), TEST_INVOCATION_ID)


    def test_get_logs_not_found_aws(self):
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"events": []}]
        self.mock_boto_client.get_paginator.return_value = mock_paginator

        logs = self.aws_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
        self.assertEqual(logs, [])

    def test_get_logs_resource_not_found_exception_aws(self):
        # Simulate ResourceNotFoundException for logs client
        # The actual exception is from botocore.exceptions.ClientError
        # and then the specific error code is checked by the AWS SDK typically.
        # For this mock, we need to ensure logs_client.exceptions.ResourceNotFoundException exists
        # and is the correct type for the except block.
        # ClientError is more realistic for boto3
        self.mock_boto_client.exceptions = Mock()
        self.mock_boto_client.exceptions.ResourceNotFoundException = ClientError(
            error_response={'Error': {'Code': 'ResourceNotFoundException', 'Message': 'Log group not found'}},
            operation_name='FilterLogEvents'
        )
        self.mock_boto_client.get_paginator.side_effect = self.mock_boto_client.exceptions.ResourceNotFoundException

        with self.assertLogs(level='WARNING') as log_watcher:
            logs = self.aws_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("Log group /aws/lambda/test-function not found" in msg for msg in log_watcher.output))

    def test_get_logs_other_exception_aws(self):
        self.mock_boto_client.get_paginator.side_effect = Exception("Some AWS SDK error")

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.aws_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("Error retrieving logs for test-function" in msg for msg in log_watcher.output))


class TestAzureLogs(unittest.TestCase):
    def setUp(self):
        self.azure_system = Azure(
            sebs_config=Mock(),
            config=Mock(spec=AzureConfig),
            cache_client=Mock(),
            docker_client=Mock(),
            logger_handlers=LoggingHandlers(logging.DEBUG)
        )
        self.azure_system.config.resources = Mock(spec=AzureResourcesConfig)
        # Mock the CLI instance, as log_analytics_workspace_id might use it
        self.azure_system.cli_instance = MagicMock()

        # Mock configuration for Log Analytics Workspace ID
        # Method 1: Mock the direct call
        self.mock_workspace_id = "test-workspace-id"
        # self.azure_system.config.resources.log_analytics_workspace_id = MagicMock(return_value=self.mock_workspace_id)
        # Method 2: If it's a property or complex attribute on resources
        # For Azure, log_analytics_workspace_id is a method of AzureResources.
        # So, we mock the method on the mocked resources object.
        type(self.azure_system.config.resources).log_analytics_workspace_id = MagicMock(return_value=self.mock_workspace_id)

        # Patch DefaultAzureCredential and LogsQueryClient
        self.mock_logs_query_client_instance = MagicMock()

        self.default_credential_patcher = patch('sebs.azure.azure.DefaultAzureCredential')
        self.mock_default_credential = self.default_credential_patcher.start()

        self.logs_query_client_patcher = patch('sebs.azure.azure.LogsQueryClient', return_value=self.mock_logs_query_client_instance)
        self.mock_logs_query_client_constructor = self.logs_query_client_patcher.start()

    def tearDown(self):
        self.default_credential_patcher.stop()
        self.logs_query_client_patcher.stop()

    def test_get_logs_success_azure(self):
        mock_response = MagicMock()
        mock_response.status = LogsQueryStatus.SUCCESS
        # Azure SDK returns tables with columns and rows
        # Our KQL query: "AppTraces | ... | project TimeGenerated, Message, customDimensions"
        # So, row will be [timestamp, message_content, custom_dimensions_dict_or_str]
        mock_table = MagicMock()
        mock_table.rows = [
            [datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc), SAMPLE_LOG_MESSAGES[0], {"InvocationId": TEST_INVOCATION_ID}],
            [datetime(2023, 1, 1, 12, 0, 1, tzinfo=timezone.utc), SAMPLE_LOG_MESSAGES[1], None],
            [datetime(2023, 1, 1, 12, 0, 2, tzinfo=timezone.utc), SAMPLE_LOG_MESSAGES[2], {"SomeKey": "SomeVal"}],
        ]
        mock_response.tables = [mock_table]
        self.mock_logs_query_client_instance.query_workspace.return_value = mock_response

        expected_logs = [
            f"{datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)} | {SAMPLE_LOG_MESSAGES[0]} | Dimensions: {{'InvocationId': '{TEST_INVOCATION_ID}'}}",
            f"{datetime(2023, 1, 1, 12, 0, 1, tzinfo=timezone.utc)} | {SAMPLE_LOG_MESSAGES[1]}",
            f"{datetime(2023, 1, 1, 12, 0, 2, tzinfo=timezone.utc)} | {SAMPLE_LOG_MESSAGES[2]} | Dimensions: {{'SomeKey': 'SomeVal'}}",
        ]

        logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
        self.assertEqual(logs, expected_logs)
        self.mock_logs_query_client_constructor.assert_called_once() # With DefaultAzureCredential
        self.mock_logs_query_client_instance.query_workspace.assert_called_once()

        args, kwargs = self.mock_logs_query_client_instance.query_workspace.call_args
        self.assertEqual(kwargs.get('workspace_id'), self.mock_workspace_id)
        self.assertIn(TEST_FUNCTION_NAME, kwargs.get('query'))
        self.assertIn(TEST_INVOCATION_ID, kwargs.get('query'))
        self.assertIsInstance(kwargs.get('timespan'), timedelta)


    def test_get_logs_partial_success_azure(self):
        mock_response = MagicMock()
        mock_response.status = LogsQueryStatus.PARTIAL
        mock_response.error = MagicMock() # Mock error object for partial
        mock_response.error.message = "Query had some issues but returned partial data."
        mock_table = MagicMock()
        mock_table.rows = [
            [datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc), SAMPLE_LOG_MESSAGES[0], {"InvocationId": TEST_INVOCATION_ID}],
        ]
        mock_response.tables = [mock_table]
        self.mock_logs_query_client_instance.query_workspace.return_value = mock_response

        expected_logs = [
            f"{datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)} | {SAMPLE_LOG_MESSAGES[0]} | Dimensions: {{'InvocationId': '{TEST_INVOCATION_ID}'}}",
        ]

        with self.assertLogs(level='WARNING') as log_watcher:
            logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, expected_logs)
            self.assertTrue(any("returned partial data" in msg for msg in log_watcher.output))


    def test_get_logs_query_failure_azure(self):
        mock_response = MagicMock()
        mock_response.status = LogsQueryStatus.FAILURE
        mock_response.error = MagicMock()
        mock_response.error.message = "Query totally failed."
        mock_response.tables = [] # No tables on failure
        self.mock_logs_query_client_instance.query_workspace.return_value = mock_response

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("Log query failed for test-function" in msg for msg in log_watcher.output))

    def test_get_logs_http_response_error_azure(self):
        self.mock_logs_query_client_instance.query_workspace.side_effect = HttpResponseError("Azure HTTP error")

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("Azure Monitor Logs query failed with HttpResponseError" in msg for msg in log_watcher.output))

    def test_get_logs_other_exception_azure(self):
        self.mock_logs_query_client_instance.query_workspace.side_effect = Exception("Some Azure SDK error")

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("An unexpected error occurred while fetching Azure logs" in msg for msg in log_watcher.output))

    def test_get_logs_no_workspace_id_azure(self):
        # Make workspace_id return None
        type(self.azure_system.config.resources).log_analytics_workspace_id = MagicMock(return_value=None)
        # Also ensure the fallback attribute doesn't exist or is None
        if hasattr(self.azure_system.config.resources, "_log_analytics_workspace_id"):
            del self.azure_system.config.resources._log_analytics_workspace_id

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.azure_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any("Failed to retrieve Log Analytics Workspace ID" in msg for msg in log_watcher.output))


class TestGCPLogs(unittest.TestCase):
    def setUp(self):
        self.gcp_system = GCP(
            system_config=Mock(),
            config=Mock(spec=GCPConfig),
            cache_client=Mock(),
            docker_client=Mock(),
            logging_handlers=LoggingHandlers(logging.DEBUG)
        )
        self.gcp_system.config.project_id = "test-gcp-project"
        # Mock credentials path for service account loading
        self.gcp_system.config.credentials = Mock(spec=GCPCredentials)
        self.gcp_system.config.credentials.path = "path/to/fake/credentials.json"

        self.mock_logging_v2_client_instance = MagicMock()

        self.service_account_patcher = patch('sebs.gcp.gcp.service_account.Credentials.from_service_account_file')
        self.mock_service_account_creds = self.service_account_patcher.start()

        self.logging_v2_client_patcher = patch('sebs.gcp.gcp.logging_v2.services.logging_service_v2.LoggingServiceV2Client', return_value=self.mock_logging_v2_client_instance)
        self.mock_logging_v2_client_constructor = self.logging_v2_client_patcher.start()

        # Patch MessageToDict as it's used for proto_payload
        self.message_to_dict_patcher = patch('sebs.gcp.gcp.MessageToDict')
        self.mock_message_to_dict = self.message_to_dict_patcher.start()
        self.mock_message_to_dict.side_effect = lambda x: {"proto_key": "proto_value", "original_payload": str(x)}

        # Mock datetime.now used in GCP log retrieval
        self.datetime_patcher = patch('sebs.gcp.gcp.datetime')
        mock_dt = self.datetime_patcher.start()
        mock_dt.now.return_value = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw) # Allow other datetime uses

    def tearDown(self):
        self.service_account_patcher.stop()
        self.logging_v2_client_patcher.stop()
        self.message_to_dict_patcher.stop()
        self.datetime_patcher.stop()

    def _create_log_entry_mock(self, timestamp, text_payload=None, json_payload=None, proto_payload=None):
        entry = MagicMock()
        entry.timestamp = timestamp
        entry.text_payload = text_payload
        # json_payload in the SDK is a Struct, which acts like a dict
        entry.json_payload = json_payload if json_payload else {} # Ensure it's dict-like or None
        # proto_payload is an Any object
        entry.proto_payload = proto_payload
        return entry

    def test_get_logs_success_gcp(self):
        ts1 = datetime(2023, 1, 1, 11, 59, 0, tzinfo=timezone.utc)
        ts2 = datetime(2023, 1, 1, 11, 59, 30, tzinfo=timezone.utc)
        ts3 = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        mock_entries = [
            self._create_log_entry_mock(timestamp=ts1, text_payload=SAMPLE_LOG_MESSAGES[0]),
            self._create_log_entry_mock(timestamp=ts2, json_payload={"message": SAMPLE_LOG_MESSAGES[1], "invocation_id_field": TEST_INVOCATION_ID}),
            self._create_log_entry_mock(timestamp=ts3, proto_payload=MagicMock(value="proto_data")),
        ]
        self.mock_logging_v2_client_instance.list_log_entries.return_value = mock_entries

        # Adjust expected logs based on how json_payload and proto_payload are stringified
        expected_logs = [
            f"{ts1.isoformat()} | {SAMPLE_LOG_MESSAGES[0]}",
            f"{ts2.isoformat()} | {{'message': '{SAMPLE_LOG_MESSAGES[1]}', 'invocation_id_field': '{TEST_INVOCATION_ID}'}}",
            f"{ts3.isoformat()} | {{'proto_key': 'proto_value', 'original_payload': '{str(mock_entries[2].proto_payload)}'}}",
        ]

        logs = self.gcp_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
        self.assertEqual(logs, expected_logs)

        self.mock_service_account_creds.assert_called_once_with(
            "path/to/fake/credentials.json",
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        self.mock_logging_v2_client_constructor.assert_called_with(credentials=self.mock_service_account_creds.return_value)
        self.mock_logging_v2_client_instance.list_log_entries.assert_called_once()

        args, kwargs = self.mock_logging_v2_client_instance.list_log_entries.call_args
        self.assertEqual(kwargs.get('resource_names'), [f"projects/{self.gcp_system.config.project_id}"])
        self.assertIn(f'resource.labels.function_name="{TEST_FUNCTION_NAME}"', kwargs.get('filter'))
        self.assertIn(f'labels.execution_id="{TEST_INVOCATION_ID}"', kwargs.get('filter'))
        self.assertIn(f'textPayload:"{TEST_INVOCATION_ID}"', kwargs.get('filter'))


    def test_get_logs_success_gcp_default_credentials(self):
        # Simulate no credentials path found
        self.gcp_system.config.credentials.path = None

        ts1 = datetime(2023, 1, 1, 11, 59, 0, tzinfo=timezone.utc)
        mock_entries = [
            self._create_log_entry_mock(timestamp=ts1, text_payload=SAMPLE_LOG_MESSAGES[0]),
        ]
        self.mock_logging_v2_client_instance.list_log_entries.return_value = mock_entries
        expected_logs = [ f"{ts1.isoformat()} | {SAMPLE_LOG_MESSAGES[0]}" ]

        with self.assertLogs(level='INFO') as log_watcher: # Check for "Using default credentials"
            logs = self.gcp_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, expected_logs)
            self.assertTrue(any("Using default credentials for Logging API" in msg for msg in log_watcher.output))

        self.mock_service_account_creds.assert_not_called() # Ensure from_service_account_file is not called
        # Default constructor is called
        self.mock_logging_v2_client_constructor.assert_called_with()


    def test_get_logs_success_gcp_credential_load_failure(self):
        # Simulate credentials path exists but loading fails
        self.mock_service_account_creds.side_effect = Exception("Failed to load SA file")

        ts1 = datetime(2023, 1, 1, 11, 59, 0, tzinfo=timezone.utc)
        mock_entries = [
            self._create_log_entry_mock(timestamp=ts1, text_payload=SAMPLE_LOG_MESSAGES[0]),
        ]
        self.mock_logging_v2_client_instance.list_log_entries.return_value = mock_entries
        expected_logs = [ f"{ts1.isoformat()} | {SAMPLE_LOG_MESSAGES[0]}" ]

        with self.assertLogs(level='ERROR') as log_watcher_error, \
             self.assertLogs(level='INFO') as log_watcher_info:
            logs = self.gcp_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, expected_logs)
            self.assertTrue(any("Failed to load credentials" in msg for msg in log_watcher_error.output))
            self.assertTrue(any("Using default credentials for Logging API" in msg for msg in log_watcher_info.output))

        self.mock_service_account_creds.assert_called_once() # Attempted to load
        self.mock_logging_v2_client_constructor.assert_called_with() # Fell back to default


    def test_get_logs_not_found_gcp(self):
        self.mock_logging_v2_client_instance.list_log_entries.return_value = []

        with self.assertLogs(level='INFO') as log_watcher:
            logs = self.gcp_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any(f"No logs found for {TEST_FUNCTION_NAME}" in msg for msg in log_watcher.output))


    def test_get_logs_google_api_error_gcp(self):
        # Using a more generic google_exceptions.GoogleAPIError as various specific ones could occur
        self.mock_logging_v2_client_instance.list_log_entries.side_effect = google_exceptions.GoogleAPIError("GCP API Error")

        with self.assertLogs(level='ERROR') as log_watcher:
            logs = self.gcp_system.get_invocation_logs(TEST_FUNCTION_NAME, TEST_INVOCATION_ID)
            self.assertEqual(logs, [])
            self.assertTrue(any(f"Error retrieving GCP logs for {TEST_FUNCTION_NAME}" in msg for msg in log_watcher.output))


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)

# Example of how to run specific tests:
# suite = unittest.TestSuite()
# suite.addTest(TestAWSLogs('test_get_logs_success_aws'))
# runner = unittest.TextTestRunner()
# runner.run(suite)

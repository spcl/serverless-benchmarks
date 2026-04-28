# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Google Cloud Platform (GCP) serverless system implementation.

This module provides the main GCP implementation with function deployment, management,
monitoring, and resource allocation. It integrates with Google Cloud Functions,
Cloud Storage, Cloud Monitoring, and Cloud Logging.

The module handles:
- Function creation, updating, and lifecycle management
- Code packaging and deployment to Cloud Functions
- HTTP and library trigger management
- Performance metrics collection via Cloud Monitoring
- Execution logs retrieval via Cloud Logging
- Cold start enforcement for benchmarking
- Storage bucket management for code deployment

Classes:
    GCP: Main system class implementing the FaaS System interface

Example:
    Basic GCP system initialization:

        config = GCPConfig(credentials, resources)
        gcp_system = GCP(system_config, config, cache, docker_client, logging_handlers)
        gcp_system.initialize()
"""

import docker
import os
import logging
import random
import re
import shutil
import time
import math
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Any, cast, Dict, Optional, Tuple, List, Type, Protocol, Union

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import google.cloud.monitoring_v3 as monitoring_v3
from google.cloud.devtools import cloudbuild_v1

from sebs.cache import Cache
from sebs.config import SeBSConfig
from sebs.benchmark import Benchmark, BenchmarkConfig
from sebs.faas.function import Function, FunctionConfig, Trigger
from sebs.faas.config import Resources
from sebs.faas.system import System
from sebs.gcp.config import (
    GCPConfig,
    GCPFunctionGen1Config,
    GCPFunctionGen2Config,
    GCPContainerConfig,
)
from sebs.gcp.resources import GCPSystemResources
from sebs.gcp.storage import GCPStorage
from sebs.gcp.function import GCPFunction, FunctionDeploymentType
from sebs.gcp.container import GCRContainer
from sebs.utils import LoggingHandlers, ColoredWrapper
from sebs.sebs_types import Language


class DeploymentStrategy(Protocol):
    """Protocol defining the interface for GCP deployment strategies.

    Different deployment types (Cloud Function Gen1, Cloud Run, etc.) implement
    this protocol to handle their specific deployment, update, and management logic.
    """

    """
        Google API is not the most robust - sometimes we need to retry REST operations.
    """
    TRANSIENT_HTTP_CODES: frozenset[int] = frozenset({429, 503})

    @staticmethod
    def _execute_with_retry(
        logging: ColoredWrapper,
        request,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 32.0,
    ) -> Dict:
        """Execute a googleapiclient request with retry logic for transient errors.

        Handles transient HTTP errors (503, 429) by retrying with exponential backoff
        and jitter. Non-transient errors are raised immediately without retry.

        Args:
            request: googleapiclient request object to execute
            max_retries: Maximum number of retry attempts (default: 5)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            max_delay: Maximum delay between retries in seconds (default: 32.0)

        Returns:
            Response dictionary from the API call

        Raises:
            HttpError: If the request fails with a non-transient error or after
                      exhausting all retry attempts
        """
        attempt = 0
        last_error = None

        while attempt <= max_retries:
            try:
                result = request.execute()
                if attempt > 0:
                    logging.info(f"Request succeeded after {attempt} retries")
                return result
            except HttpError as e:
                status_code = e.resp.status
                last_error = e

                # Only retry on transient errors
                if status_code not in DeploymentStrategy.TRANSIENT_HTTP_CODES:
                    raise

                # Check if we have retries left
                if attempt >= max_retries:
                    logging.error(
                        f"Max retries ({max_retries}) exhausted, failing with status {status_code}"
                    )
                    raise

                # Calculate delay with exponential backoff and jitter
                delay = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)

                if attempt == 0:
                    logging.warning(
                        f"Transient error {status_code}, retrying "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                else:
                    logging.info(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s backoff")

                time.sleep(delay)
                attempt += 1

        # This should not be reached, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected state in retry logic")

    def create(
        self,
        func_name: str,
        code_package: Benchmark,
        function_cfg: FunctionConfig,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Create function/service without waiting for deployment to complete.

        Args:
            func_name: Name for the function/service
            code_package: Benchmark package with code
            function_cfg: Function configuration (memory, timeout, etc.)
            envs: Environment variables
            container_uri: Container image URI (for container deployments)
        """
        ...

    def update_code(
        self,
        function: "GCPFunction",
        code_package: Benchmark,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Update function/service code without waiting for deployment to complete.

        Args:
            function: Existing function instance
            code_package: New benchmark package
            envs: Environment variables
            container_uri: Container image URI (for container deployments)
        """
        ...

    def update_config(
        self,
        function: "GCPFunction",
        envs: Dict,
    ) -> int:
        """Update function/service configuration (memory, timeout, env vars).

        Args:
            function: Function instance to update
            envs: Environment variables

        Returns:
            Version number after update
        """
        ...

    def wait_for_deployment(
        self,
        func_name: str,
    ) -> None:
        """Wait for deployment to complete (build polling for Gen1, operation wait for Run).

        Args:
            func_name: Name of the function/service to wait for
        """
        ...

    def allow_public_access(self, project_name: str, location: str, func_name: str) -> None:
        """Set IAM policy for public access.

        Args:
            func_name: Function/service name
            full_resource_name: Full GCP resource name
        """
        ...

    def create_trigger(
        self,
        func_name: str,
    ) -> str:
        """Create HTTP trigger and return the invoke URL.

        Args:
            func_name: Function/service name

        Returns:
            HTTP trigger URL
        """
        ...

    def update_envs(
        self,
        full_function_name: str,
        envs: Dict,
    ) -> Dict:
        """Merge new environment variables with existing ones.

        Args:
            full_function_name: Full GCP resource name
            envs: New environment variables to add/update

        Returns:
            Merged environment variables dictionary
        """
        ...

    def generate_runtime_envs(self) -> Dict:
        """Generate deployment-runtime environment variables."""
        ...

    def is_deployed(
        self,
        func_name: str,
        versionId: int = -1,
    ) -> Tuple[bool, int]:
        """Check if function/service is deployed.

        Args:
            func_name: Function/service name
            versionId: Optional specific version ID to verify (-1 to check any)

        Returns:
            Tuple of (is_deployed, current_version_id)
        """
        ...

    def delete_function(
        self,
        func_name: str,
    ) -> None:
        """Delete the function/service.

        Args:
            func_name: Function/service name to delete
        """
        ...

    @staticmethod
    def get_full_function_name(project_name: str, location: str, func_name: str) -> str:
        """Generate the fully qualified function name for GCP API calls.

        Args:
            project_name: GCP project ID
            location: GCP region/location
            func_name: Function name

        Returns:
            Fully qualified function name in GCP format
        """
        ...

    def function_exists(self, project_name: str, location: str, func_name: str) -> Any:
        """Check whether the function or service exists.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function or service name.

        Returns:
            True if the resource exists, otherwise False.
        """
        ...

    def download_execution_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
    ) -> None:
        """Populate provider execution times for completed invocations.

        Args:
            function_name: Function or service name.
            start_time: Start timestamp for metric collection.
            end_time: End timestamp for metric collection.
            requests: Invocation results keyed by request ID.
        """
        ...

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, metrics: Dict
    ) -> None:
        """Populate metrics with data from cloud monitoring.

        Args:
            function_name: Function or service name.
            start_time: Start timestamp for metric collection.
            end_time: End timestamp for metric collection.
            metrics: Dictionary mapping metric names to found values.
        """
        ...


class CloudRunMetricsHelper:
    """Helpers shared by Cloud Run services and Cloud Functions gen2."""

    @staticmethod
    def download_execution_metrics(
        logging: ColoredWrapper,
        project_name: str,
        service_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
        label: str,
    ) -> None:
        """Download execution times from Cloud Run request logs."""
        import google.cloud.logging as gcp_logging

        timestamps = []
        for timestamp in [start_time, end_time + 1]:
            utc_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            timestamps.append(utc_date.strftime("%Y-%m-%dT%H:%M:%SZ"))

        logging_client = gcp_logging.Client()
        entries = logging_client.list_entries(
            filter_=(
                'resource.type = "cloud_run_revision" '
                'logName = "projects/'
                f'{project_name}/logs/run.googleapis.com%2Frequests" '
                f'resource.labels.service_name = "{service_name}" '
                f'timestamp >= "{timestamps[0]}" '
                f'timestamp <= "{timestamps[1]}"'
            ),
            page_size=1000,
        )

        found_metrics = 0
        total_entries = 0
        for entry in entries:
            total_entries += 1
            trace_id = CloudRunMetricsHelper.extract_trace_id(entry)
            if trace_id is None or trace_id not in requests:
                continue

            execution_time_us = CloudRunMetricsHelper.extract_latency_us(entry)
            if execution_time_us is None:
                continue

            requests[trace_id].provider_times.execution = execution_time_us
            found_metrics += 1

        logging.info(
            f"{label}: Received {total_entries} log entries, found time metrics for "
            f"{found_metrics} out of {len(requests.keys())} invocations."
        )

    @staticmethod
    def download_metrics(
        project_name: str,
        service_name: str,
        start_time: int,
        end_time: int,
        metrics: Dict,
    ) -> None:
        """Download Cloud Run monitoring metrics."""
        available_metrics = [
            ("container/billable_instance_time", "delta", "double"),
            ("container/instance_count", "gauge", "int64"),
            ("container/max_request_concurrencies", "delta", "distribution"),
            ("container/memory/utilizations", "delta", "distribution"),
            ("container/cpu/utilizations", "delta", "distribution"),
            ("container/cpu/allocation_time", "delta", "double"),
            ("container/memory/allocation_time", "delta", "double"),
            ("container/network/sent_bytes_count", "delta", "int64"),
            ("container/network/received_bytes_count", "delta", "int64"),
            ("container/startup_latencies", "delta", "distribution"),
            ("request_count", "delta", "int64"),
            ("request_latencies", "distribution", "distribution"),
            ("request_latency/e2e_latencies", "delta", "distribution"),
            ("request_latency/ingress_to_region", "delta", "distribution"),
            ("request_latency/pending", "delta", "distribution"),
            ("request_latency/response_egress", "delta", "distribution"),
            ("request_latency/routing", "delta", "distribution"),
            ("request_latency/user_execution", "delta", "distribution"),
        ]

        client = monitoring_v3.MetricServiceClient()
        project_path = client.common_project_path(project_name)

        _, end_time_seconds = math.modf(end_time)
        _, start_time_seconds = math.modf(start_time)
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(end_time_seconds) + 300},
                "start_time": {"seconds": int(start_time_seconds)},
            }
        )

        for metric, kind, value_type in available_metrics:
            metrics[metric] = []
            flt = (
                f'metric.type = "run.googleapis.com/{metric}" '
                f'AND resource.type = "cloud_run_revision" '
                f'AND resource.labels.service_name = "{service_name}"'
            )
            list_request = monitoring_v3.ListTimeSeriesRequest(
                name=project_path,
                filter=flt,
                interval=interval,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            )
            for result in client.list_time_series(list_request):
                revision = result.resource.labels.get("revision_name")
                for point in result.points:
                    if value_type == "distribution":
                        sq_dev = point.value.distribution_value.sum_of_squared_deviation
                        metrics[metric].append(
                            {
                                "kind": kind,
                                "revision": revision,
                                "mean_value": point.value.distribution_value.mean,
                                "squared_deviations": sq_dev,
                                "count": point.value.distribution_value.count,
                                "ts": point.interval.end_time.timestamp(),
                            }
                        )
                    else:
                        value: int | float
                        value = (
                            point.value.int64_value
                            if value_type == "int64"
                            else point.value.double_value
                        )
                        metrics[metric].append(
                            {
                                "revision": revision,
                                "value": value,
                                "kind": kind,
                                "ts": point.interval.end_time.timestamp(),
                            }
                        )

    @staticmethod
    def extract_trace_id(entry) -> Optional[str]:
        """Extract the trace ID from a Cloud Run log entry.

        Args:
            entry: Log entry to inspect.

        Returns:
            Trace ID if present, otherwise ``None``.
        """
        trace = getattr(entry, "trace", None)
        if not isinstance(trace, str) or "/traces/" not in trace:
            return None
        return trace.rsplit("/traces/", 1)[1]

    @staticmethod
    def extract_latency_us(entry) -> Optional[int]:
        """Extract request latency from a Cloud Run log entry.

        Args:
            entry: Log entry to inspect.

        Returns:
            Request latency in microseconds, or ``None`` if unavailable.
        """
        http_request = getattr(entry, "http_request", None)
        if http_request is None:
            return None

        latency = http_request.get("latency")
        if not isinstance(latency, str):
            return None

        try:
            return int(float(latency[:-1]) * 1_000_000)
        except (ValueError, TypeError):
            return None


class CloudFunctionGen1Strategy(DeploymentStrategy):
    """Deployment strategy for Google Cloud Functions Gen1."""

    def __init__(self, storage: GCPStorage, config: GCPConfig, logging_handlers: ColoredWrapper):
        """Initialize strategy with reference to config
        and main GCP instance loggers.

        Args:
            storage: GCP storage instance
            config: GPC configuration
            logging: main logging handlers for status reporting
        """
        super().__init__()
        self.storage = storage
        self.config = config
        self.logging = logging_handlers

        self.function_client = build("cloudfunctions", "v1", cache_discovery=False)

    @staticmethod
    def get_full_function_name(project_name: str, location: str, func_name: str) -> str:
        """Build the fully qualified Cloud Functions resource name.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function name.

        Returns:
            Fully qualified Cloud Functions resource name.
        """
        return f"projects/{project_name}/locations/{location}/functions/{func_name}"

    def function_exists(self, project_name: str, location: str, func_name: str) -> Any:
        """Check whether the Cloud Function exists.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function name.

        Returns:
            True if the function exists, otherwise False.
        """
        full_resource_name = self.get_full_function_name(project_name, location, func_name)
        get_req = (
            self.function_client.projects().locations().functions().get(name=full_resource_name)
        )

        try:
            self._execute_with_retry(self.logging, get_req)
            return True
        except HttpError as e:
            if e.resp.status == 404:
                return False
            raise RuntimeError(f"Error checking function existence: {e}") from None

    def create(
        self,
        func_name: str,
        code_package: Benchmark,
        function_cfg: FunctionConfig,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Create a Cloud Function Gen1."""
        project_name = self.config.project_name
        location = self.config.region
        full_func_name = self.get_full_function_name(project_name, location, func_name)
        language_runtime = code_package.language_version
        timeout = code_package.benchmark_config.timeout
        memory = code_package.benchmark_config.memory
        architecture = function_cfg.architecture.value

        package = code_package.code_location
        if package is None:
            raise RuntimeError("Code location is not set for GCP deployment")

        code_package_name = cast(str, os.path.basename(package))
        code_package_name = f"{architecture}-{code_package_name}"
        code_bucket = self.storage.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
        code_prefix = os.path.join(code_package.benchmark, code_package_name)
        self.storage.upload(code_bucket, package, code_prefix)

        self.logging.info("Uploading function {} code to {}".format(func_name, code_bucket))

        dep_config = self.config.deployment_config.function_gen1_config

        function_body = {
            "name": full_func_name,
            "entryPoint": (
                "org.serverlessbench.Handler"
                if code_package.language == Language.JAVA
                else "handler"
            ),
            "runtime": code_package.language_name + language_runtime.replace(".", ""),
            "availableMemoryMb": memory,
            "timeout": str(timeout) + "s",
            "httpsTrigger": {},
            "ingressSettings": "ALLOW_ALL",
            "sourceArchiveUrl": "gs://" + code_bucket + "/" + code_prefix,
            "environmentVariables": envs,
            "minInstances": dep_config.min_instances,
            "maxInstances": dep_config.max_instances,
        }

        create_req = (
            self.function_client.projects()
            .locations()
            .functions()
            .create(
                location="projects/{project_name}/locations/{location}".format(
                    project_name=project_name, location=location
                ),
                body=function_body,  # type: ignore[arg-type]
            )
        )

        self._execute_with_retry(self.logging, create_req)
        self.logging.info(f"Function {func_name} is creating - GCP build&deployment is started!")

    def update_code(
        self,
        function: "GCPFunction",
        code_package: Benchmark,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Update Cloud Function Gen1 code."""
        if code_package.code_location is None:
            raise RuntimeError("Code location is not set for GCP deployment")

        language_runtime = code_package.language_version
        function_cfg = FunctionConfig.from_benchmark(code_package)
        architecture = function_cfg.architecture.value
        code_package_name = os.path.basename(code_package.code_location)
        code_package_name = f"{architecture}-{code_package_name}"

        bucket = function.code_bucket(code_package.benchmark, self.storage)
        self.storage.upload(bucket, code_package.code_location, code_package_name)

        self.logging.info(f"Uploaded new code package to {bucket}/{code_package_name}")
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        dep_config = self.config.deployment_config.function_gen1_config

        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(
                name=full_func_name,
                body={
                    "name": full_func_name,
                    "entryPoint": (
                        "org.serverlessbench.Handler"
                        if code_package.language == Language.JAVA
                        else "handler"
                    ),
                    "runtime": code_package.language_name + language_runtime.replace(".", ""),
                    "availableMemoryMb": function.config.memory,
                    "timeout": str(function.config.timeout) + "s",
                    "httpsTrigger": {},
                    "sourceArchiveUrl": "gs://" + bucket + "/" + code_package_name,
                    "environmentVariables": envs,
                    "minInstances": dep_config.min_instances,
                    "maxInstances": dep_config.max_instances,
                },
            )
        )

        self._execute_with_retry(self.logging, req)
        self.logging.info(f"Function {function.name} code update initiated")

    def update_config(self, function: "GCPFunction", envs: Dict) -> int:
        """Update Cloud Function Gen1 configuration."""
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        dep_config = self.config.deployment_config.function_gen1_config

        body = {
            "availableMemoryMb": function.config.memory,
            "timeout": str(function.config.timeout) + "s",
            "minInstances": dep_config.min_instances,
            "maxInstances": dep_config.max_instances,
        }

        if len(envs) > 0:
            body["environmentVariables"] = envs
            update_mask = "availableMemoryMb,timeout,environmentVariables,minInstances,maxInstances"
        else:
            update_mask = "availableMemoryMb,timeout,minInstances,maxInstances"

        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(
                name=full_func_name,
                updateMask=update_mask,
                body=body,  # type: ignore[arg-type]
            )
        )

        res = self._execute_with_retry(self.logging, req)
        expected_version = int(res["metadata"]["versionId"])

        self.logging.info(f"Function {function.name} configuration update initiated")

        # Wait for deployment to become ACTIVE with expected version
        # Configuration updates don't trigger builds but still need deployment time
        current_version = self._wait_for_active_status(function.name, expected_version, timeout=60)
        self.logging.info("Published new function configuration.")

        return current_version

    def wait_for_deployment(
        self,
        func_name: str,
    ) -> None:
        """Wait for Cloud Function Gen1 deployment via build polling."""
        # Poll build status until completion or failure
        build_found = self._wait_for_build_and_poll(func_name)
        if not build_found:
            raise RuntimeError(f"No build operation found for {func_name}!")

        # Wait for deployment to become ACTIVE
        self._wait_for_active_status(func_name)

    def allow_public_access(self, project_name: str, location: str, func_name: str) -> None:
        """Set IAM policy for public access on Cloud Function Gen1."""

        full_resource_name = self.get_full_function_name(project_name, location, func_name)

        allow_unauthenticated_req = (
            self.function_client.projects()
            .locations()
            .functions()
            .setIamPolicy(
                resource=full_resource_name,
                body={
                    "policy": {
                        "bindings": [
                            {
                                "role": "roles/cloudfunctions.invoker",
                                "members": ["allUsers"],
                            }
                        ]
                    }
                },
            )
        )

        try:
            self._execute_with_retry(self.logging, allow_unauthenticated_req)
        except HttpError as e:
            raise RuntimeError(
                f"Failed to configure function {full_resource_name} "
                f"for unauthenticated invocations! Error: {e}"
            )

    def create_trigger(self, func_name: str) -> str:
        """Create HTTP trigger and return the invoke URL for Cloud Function.

        Args:
            func_name: Function name

        Returns:
            HTTP trigger URL
        """
        project_name = self.config.project_name
        location = self.config.region
        full_func_name = self.get_full_function_name(project_name, location, func_name)
        get_req = self.function_client.projects().locations().functions().get(name=full_func_name)
        func_details = self._execute_with_retry(self.logging, get_req)
        invoke_url = func_details["httpsTrigger"]["url"]
        self.logging.info(f"Function {func_name} - HTTP trigger URL: {invoke_url}")
        return invoke_url

    def update_envs(self, full_function_name: str, envs: Dict) -> Dict:
        """Merge new environment variables with existing Cloud Function environment.

        Args:
            full_function_name: Fully qualified function name
            envs: New environment variables to add/update

        Returns:
            Merged environment variables dictionary
        """
        get_req = (
            self.function_client.projects().locations().functions().get(name=full_function_name)
        )
        response = self._execute_with_retry(self.logging, get_req)

        # preserve old variables while adding new ones.
        # but for conflict, we select the new one
        if "environmentVariables" in response:
            envs = {**response["environmentVariables"], **envs}  # type: ignore[typeddict-item]

        return envs

    def generate_runtime_envs(self) -> Dict:
        """Return runtime environment variables for Gen1 deployments.

        Returns:
            Empty dictionary because Gen1 does not require runtime overrides.
        """
        return {}

    def is_deployed(self, func_name: str, versionId: int = -1) -> Tuple[bool, int]:
        """Check if Cloud Function is deployed and optionally verify its version.

        Args:
            func_name: Name of the function to check
            versionId: Optional specific version ID to verify (-1 to check any)

        Returns:
            Tuple of (is_deployed, current_version_id)
        """
        name = self.get_full_function_name(self.config.project_name, self.config.region, func_name)
        status_req = self.function_client.projects().locations().functions().get(name=name)
        status_res = self._execute_with_retry(self.logging, status_req)
        if versionId == -1:
            return (status_res["status"] == "ACTIVE", status_res["versionId"])
        else:
            return (status_res["versionId"] == versionId, status_res["versionId"])

    def delete_function(self, func_name: str) -> None:
        """Delete a Google Cloud Function.

        Args:
            func_name: Name of the function to delete
        """
        self.logging.info(f"Deleting function {func_name}")

        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )

        try:
            delete_req = (
                self.function_client.projects().locations().functions().delete(name=full_func_name)
            )
            self._execute_with_retry(self.logging, delete_req)
            self.logging.info(f"Function {func_name} deleted successfully")
        except HttpError as e:
            if e.resp.status == 404:
                self.logging.error(f"Function {func_name} does not exist!")
            else:
                self.logging.error(f"Failed to delete function {func_name}: {e}")
                raise

    def download_execution_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
    ) -> None:
        """Download execution times for Cloud Functions Gen1 from Cloud Logging."""

        from google.api_core import exceptions
        from time import sleep
        import google.cloud.logging as gcp_logging

        def wrapper(gen):
            """Yield entries while backing off on transient quota errors."""
            while True:
                try:
                    yield next(gen)
                except StopIteration:
                    break
                except exceptions.ResourceExhausted:
                    self.logging.info("Google Cloud resources exhausted, sleeping 30s")
                    sleep(30)

        timestamps = []
        for timestamp in [start_time, end_time + 5]:
            utc_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            timestamps.append(utc_date.strftime("%Y-%m-%dT%H:%M:%SZ"))

        logging_client = gcp_logging.Client()
        logger = logging_client.logger("cloudfunctions.googleapis.com%2Fcloud-functions")
        invocations = logger.list_entries(
            filter_=(
                f'resource.labels.function_name = "{function_name}" '
                f'timestamp >= "{timestamps[0]}" '
                f'timestamp <= "{timestamps[1]}"'
            ),
            page_size=1000,
        )

        invocations_processed = 0
        if hasattr(invocations, "pages"):
            pages = list(wrapper(invocations.pages))
        else:
            pages = [list(wrapper(invocations))]

        entries = 0
        for page in pages:
            for invoc in page:
                entries += 1
                if "execution took" not in invoc.payload:
                    continue
                trace_id = self._extract_trace_id(invoc)
                if trace_id is None or trace_id not in requests:
                    continue

                regex_result = re.search(r"\d+ ms", invoc.payload)
                assert regex_result
                exec_time = regex_result.group().split()[0]
                requests[trace_id].provider_times.execution = int(exec_time) * 1000
                invocations_processed += 1

        self.logging.info(
            f"GCP Gen1: Received {entries} entries, found time metrics for "
            f"{invocations_processed} out of {len(requests.keys())} invocations."
        )

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, metrics: Dict
    ) -> None:
        """
        Download monitoring metrics for Cloud Functions Gen1.
        Use metrics to find estimated values for maximum memory used, active instances
        and network traffic.
        https://cloud.google.com/monitoring/api/metrics_gcp#gcp-cloudfunctions
        """

        # Set expected metrics here
        available_metrics = ["execution_times", "user_memory_bytes", "network_egress"]

        client = monitoring_v3.MetricServiceClient()
        project_name = client.common_project_path(self.config.project_name)

        end_time_nanos, end_time_seconds = math.modf(end_time)
        start_time_nanos, start_time_seconds = math.modf(start_time)

        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(end_time_seconds) + 60},
                "start_time": {"seconds": int(start_time_seconds)},
            }
        )

        for metric in available_metrics:

            metrics[metric] = []

            list_request = monitoring_v3.ListTimeSeriesRequest(
                name=project_name,
                filter='metric.type = "cloudfunctions.googleapis.com/function/{}"'.format(metric),
                interval=interval,
            )

            results = client.list_time_series(list_request)
            for result in results:
                if result.resource.labels.get("function_name") == function_name:
                    for point in result.points:
                        metrics[metric] += [
                            {
                                "mean_value": point.value.distribution_value.mean,
                                "executions_count": point.value.distribution_value.count,
                            }
                        ]

    @staticmethod
    def _extract_trace_id(entry) -> Optional[str]:
        """Extract the trace ID from a Cloud Functions log entry.

        Args:
            entry: Log entry to inspect.

        Returns:
            Trace ID if present, otherwise ``None``.
        """
        trace = getattr(entry, "trace", None)
        if not isinstance(trace, str) or "/traces/" not in trace:
            return None
        return trace.rsplit("/traces/", 1)[1]

    def _wait_for_build_and_poll(
        self, func_name: str, timeout: int = 300, poll_interval: int = 2
    ) -> bool:
        """Wait for build to start, get build name, and poll until completion.

        Since GCP operations typically don't immediately return a build name, this function
        waits for the build to start, retrieves the build name from the function's
        metadata, and then polls the build status.

        Args:
            func_name: Name of the function being built
            timeout: Maximum time to wait in seconds (default: 300)
            poll_interval: Seconds between polling attempts (default: 2)

        Returns:
            True if a build was found and completed successfully, False if no build was found

        Raises:
            RuntimeError: If build fails
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        begin = time.time()
        build_name = None
        previous_build_id = None

        # First, try to get the current build ID to compare against
        try:
            get_req = (
                self.function_client.projects().locations().functions().get(name=full_func_name)
            )
            func_details = self._execute_with_retry(self.logging, get_req)
            if "buildId" in func_details:
                previous_build_id = func_details["buildId"]
        except HttpError:
            pass

        # Wait for build to start and get build name
        self.logging.info(f"Waiting for build to start for function {func_name}...")
        while build_name is None:
            if time.time() - begin > timeout:
                self.logging.warning(
                    f"No build found for {func_name} after {timeout}s - "
                    "might be a configuration-only update"
                )
                return False

            try:
                # Get function details to find the build
                get_req = (
                    self.function_client.projects().locations().functions().get(name=full_func_name)
                )
                func_details = self._execute_with_retry(self.logging, get_req)

                # Check if there's a new build in progress
                if "buildId" in func_details:
                    build_id = func_details["buildId"]
                    # Only consider it a new build if it's different from the previous one
                    if previous_build_id is None or build_id != previous_build_id:
                        # Construct build name from build ID
                        build_name = (
                            f"projects/{self.config.project_name}/locations/"
                            f"{self.config.region}/builds/{build_id}"
                        )
                        self.logging.info(f"Found build {build_id} for function {func_name}!")
                        break
            except HttpError as e:
                self.logging.debug(f"Error getting function details: {e}")

            time.sleep(poll_interval)

        # Now poll the build status
        if build_name:
            self._poll_build_status(build_name, func_name, timeout)
            return True

        return False

    def _wait_for_active_status(
        self, func_name: str, expected_version: Optional[int] = None, timeout: int = 60
    ) -> int:
        """Wait for function to reach ACTIVE status after build completes.

        After a build completes, the function may be in DEPLOY_IN_PROGRESS state
        for a short time. This function polls until the status becomes ACTIVE.
        Furthermore, we handle HTTP errors:
        * 503 / 429 transient backend errors — GCP Cloud Functions v1
            can periodically returns these; they are not deployment failures.

        Args:
            func_name: Name of the function to check
            expected_version: Optional version ID to verify (None to skip version check)
            timeout: Maximum time to wait in seconds (default: 60)

        Returns:
            Current version ID of the function

        Raises:
            RuntimeError: If deployment fails or timeout is reached
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        begin = time.time()
        last_status: Optional[str] = None

        self.logging.info(f"Waiting for function {func_name} to become ACTIVE...")

        while True:

            elapsed = time.time() - begin
            if elapsed > timeout:
                raise RuntimeError(
                    f"Timeout waiting for function {func_name} to become ACTIVE "
                    f"after {elapsed:.0f}s. Last status: {last_status}"
                )

            get_req = (
                self.function_client.projects().locations().functions().get(name=full_func_name)
            )
            func_details = self._execute_with_retry(self.logging, get_req)

            status = func_details["status"]
            current_version = int(func_details["versionId"])

            if status != last_status:
                last_status = status

            if status == "ACTIVE":
                # Check version if specified
                if expected_version is not None and current_version != expected_version:
                    self.logging.warning(
                        f"Function {func_name} is ACTIVE but version mismatch: "
                        f"expected {expected_version}, got {current_version}"
                    )
                    # Continue waiting as version might still be updating
                else:
                    self.logging.info(f"Function {func_name} is ACTIVE (version {current_version})")
                    return current_version
            elif status == "DEPLOY_IN_PROGRESS":
                self.logging.debug(f"Function {func_name} deployment in progress...")
            else:
                # Unexpected status
                self.logging.error(f"Function {func_name} has unexpected status: {status}")
                raise RuntimeError(
                    f"Function {func_name} deployment failed with status: {status}"
                ) from None

            time.sleep(2)

    def _poll_build_status(self, build_name: str, func_name: str, timeout: int = 300) -> None:
        """Poll build operation until completion or failure.

        Monitors a Cloud Build operation, waiting for it to complete successfully
        or fail. Provides detailed error information if the build fails.

        Args:
            build_name: Fully qualified build name from GCP API
            func_name: Function name for logging purposes
            timeout: Maximum time to wait in seconds (default: 300)

        Raises:
            RuntimeError: If build fails or timeout is reached
        """
        build_client = cloudbuild_v1.CloudBuildClient()
        begin = time.time()

        while True:
            build_status = build_client.get_build(name=build_name)

            if build_status.status == cloudbuild_v1.Build.Status.SUCCESS:
                self.logging.info(f"Function {func_name} - build completed successfully!")
                break
            elif build_status.status == cloudbuild_v1.Build.Status.FAILURE:
                self.logging.error(f"Failed to build function: {func_name}")
                self.logging.error(f"Reasons: {build_status.failure_info.detail}")
                self.logging.error(f"URL for detailed error: {build_status.log_url}")
                raise RuntimeError(f"Build failed for function {func_name}!") from None
            elif build_status.status in (
                cloudbuild_v1.Build.Status.CANCELLED,
                cloudbuild_v1.Build.Status.TIMEOUT,
            ):
                self.logging.error(f"Build was cancelled or timed out for function: {func_name}")
                self.logging.error(f"URL for detailed error: {build_status.log_url}")
                raise RuntimeError(f"Build failed for function {func_name}!") from None

            if time.time() - begin > timeout:
                self.logging.error(
                    f"Failed to build function: {func_name} after {timeout} seconds!"
                )
                raise RuntimeError(f"Build timeout for function {func_name}!") from None

            time.sleep(3)


class RunContainerStrategy(DeploymentStrategy):
    """Deployment strategy for Google Cloud Run containers (Gen1)."""

    def __init__(self, config: GCPConfig, logging_handlers: ColoredWrapper):
        """Initialize strategy with reference to config
        and main GCP instance loggers.

        Args:
            config: GPC configuration
            logging: main logging handlers for status reporting
        """
        # Container-based functions are created via run-client
        self.run_client = build("run", "v2", cache_discovery=False)
        self.config = config
        self.logging = logging_handlers

    @staticmethod
    def get_full_function_name(project_name: str, location: str, service_name: str) -> str:
        """Build the fully qualified Cloud Run service resource name.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            service_name: Cloud Run service name.

        Returns:
            Fully qualified Cloud Run service resource name.
        """
        return f"projects/{project_name}/locations/{location}/services/{service_name}"

    def function_exists(self, project_name: str, location: str, func_name: str) -> Any:
        """Check whether the Cloud Run service exists.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Cloud Run service name.

        Returns:
            True if the service exists, otherwise False.
        """
        full_resource_name = self.get_full_function_name(project_name, location, func_name)
        get_req = self.run_client.projects().locations().services().get(name=full_resource_name)

        try:
            self._execute_with_retry(self.logging, get_req)
            return True
        except HttpError:
            return False

    def _transform_service_envs(self, envs: dict) -> list:
        """Convert environment variables into the Cloud Run API format.

        Args:
            envs: Key-value environment mapping.

        Returns:
            List of Cloud Run environment variable descriptors.
        """
        return [{"name": k, "value": v} for k, v in envs.items()]

    def _service_body(
        self,
        benchmark_config: BenchmarkConfig | FunctionConfig,
        envs_list: Dict,
        container_uri: str,
    ) -> Dict:
        """Build the Cloud Run service body for create and update requests.

        Args:
            benchmark_config: Benchmark or function configuration providing memory and timeout.
            envs_list: Environment variables to inject into the container.
            container_uri: Container image URI to deploy.

        Returns:
            Cloud Run service body payload.
        """

        dep_config = self.config.deployment_config.container_config

        timeout = benchmark_config.timeout
        memory = benchmark_config.memory

        execution_environment = f"EXECUTION_ENVIRONMENT_{dep_config.environment.upper()}"

        return {
            "template": {
                "containers": [
                    {
                        "image": container_uri,  # type: ignore[typeddict-item]
                        "ports": [{"containerPort": 8080}],
                        "env": self._transform_service_envs(envs_list),
                        "resources": {
                            "limits": {
                                "memory": f"{memory if memory >= 512 else 512}Mi",
                                "cpu": str(dep_config.vcpus),
                            },
                            "cpuIdle": dep_config.cpu_throttle,
                            "startupCpuBoost": dep_config.cpu_boost,
                        },
                    }
                ],
                "timeout": f"{timeout}s",
                "maxInstanceRequestConcurrency": dep_config.gcp_concurrency,
                "execution_environment": execution_environment,
            },
            "scaling": {
                "minInstanceCount": dep_config.min_instances,
                "maxInstanceCount": dep_config.max_instances,
            },
            "ingress": "INGRESS_TRAFFIC_ALL",
        }

    def create(
        self,
        func_name: str,
        code_package: Benchmark,
        function_cfg: FunctionConfig,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Create a Cloud Run service."""
        if container_uri is None:
            raise RuntimeError("Container URI is required for Cloud Run deployment")

        project_name = self.config.project_name
        location = self.config.region

        self.logging.info(
            f"Deploying GCP Cloud Run container service {func_name} from {container_uri}"
        )

        parent = f"projects/{project_name}/locations/{location}"
        service_body = self._service_body(code_package.benchmark_config, envs, container_uri)
        create_req = (
            self.run_client.projects()
            .locations()
            .services()
            .create(
                parent=parent,
                serviceId=func_name,
                body=service_body,  # type: ignore[arg-type]
            )
        )

        self._operation_response = create_req.execute()
        self.logging.info(
            f"Creating Cloud Run service {func_name}, waiting for operation completion..."
        )

    def update_code(
        self,
        function: GCPFunction,
        code_package: Benchmark,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Update Cloud Run service code."""
        if container_uri is None:
            raise RuntimeError("Container URI is required for Cloud Run deployment")

        full_service_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        self.logging.info(f"Updating Cloud Run service {function.name} with image: {container_uri}")

        service_body = self._service_body(code_package.benchmark_config, envs, container_uri)

        # We are using the broad "template" for updateMask.
        # We noticed that when using selective updates with `template.containers`,
        # GCP would not create a new revision when using the same image tag -
        # even when the tag now links to a different digest.
        req = (
            self.run_client.projects()
            .locations()
            .services()
            .patch(  # type: ignore[arg-type]
                name=full_service_name,
                body=service_body,  # type: ignore[arg-type]
                updateMask="template",
            )
        )

        self._operation_response = req.execute()
        self.logging.info(
            f"Patch request sent for Cloud Run service {function.name}, waiting for operation..."
        )

    def update_config(self, function: GCPFunction, envs: Dict) -> int:
        """Update Cloud Run service configuration."""

        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        # We are using the broad "template" for updateMask.
        # We noticed that when using selective updates with `template.containers`,
        # GCP would not create a new revision when using the same image tag -
        # even when the tag now links to a different digest.

        container_uri = function.container_uri()
        if container_uri is None:
            raise RuntimeError("Container URI is required for Cloud Run deployment")

        service_body = self._service_body(function.config, envs, container_uri)
        req = (
            self.run_client.projects()
            .locations()
            .services()
            .patch(  # type: ignore[arg-type]
                name=full_func_name,
                body=service_body,  # type: ignore[arg-type]
                updateMask="template",
            )
        )

        self._operation_response = req.execute()
        self.logging.info(
            f"Patch request sent for Cloud Run config {function.name}, waiting for operation..."
        )

        self.wait_for_deployment(function.name)

        return 0

    def wait_for_deployment(
        self,
        func_name: str,
    ) -> None:
        """Wait for Cloud Run deployment via operation wait."""
        if not hasattr(self, "_operation_response"):
            raise RuntimeError("No operation to wait for - create/update not called")

        op_name = self._operation_response["name"]
        self.logging.info(f"Waiting for operation: {op_name}")
        op_res = self.run_client.projects().locations().operations().wait(name=op_name).execute()

        if "error" in op_res:
            raise RuntimeError(f"Cloud Run deployment failed: {op_res['error']}")

        # Get service details to check revision
        full_service_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        svc = (
            self.run_client.projects().locations().services().get(name=full_service_name).execute()
        )

        latest_revision = svc.get("latestReadyRevision", "unknown")
        self.logging.info(
            f"Cloud Run service {func_name} deployed. " f"Latest revision: {latest_revision}"
        )

        delattr(self, "_operation_response")

    def allow_public_access(self, project_name: str, location: str, func_name: str) -> None:
        """Set IAM policy for public access on Cloud Run."""

        full_resource_name = self.get_full_function_name(project_name, location, func_name)

        allow_unauthenticated_req = (
            self.run_client.projects()
            .locations()
            .services()
            .setIamPolicy(
                resource=full_resource_name,
                body={
                    "policy": {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}
                },
            )
        )

        try:
            self._execute_with_retry(self.logging, allow_unauthenticated_req)
        except HttpError as e:
            raise RuntimeError(
                f"Failed to configure function {full_resource_name} "
                f"for unauthenticated invocations! Error: {e}"
            )

    def create_trigger(self, func_name: str) -> str:
        """Create HTTP trigger and return the invoke URL for Cloud Run service.

        Args:
            func_name: Service name

        Returns:
            HTTP trigger URL
        """
        project_name = self.config.project_name
        location = self.config.region
        service_id = func_name.lower()
        full_service_name = self.get_full_function_name(project_name, location, service_id)

        self.logging.info(f"Waiting for service {full_service_name} to be ready...")
        deployed = False
        begin = time.time()
        while not deployed:
            svc = (
                self.run_client.projects()
                .locations()
                .services()
                .get(name=full_service_name)
                .execute()
            )
            condition = svc.get("terminalCondition", {})
            if condition.get("type") == "Ready" and condition.get("state") == "CONDITION_SUCCEEDED":
                deployed = True
            else:
                time.sleep(3)

            if time.time() - begin > 300:
                self.logging.error(f"Failed to deploy service: {func_name}")
                raise RuntimeError("Deployment timeout!")

        self.logging.info(f"Service {func_name} - deployed!")
        invoke_url = svc["uri"]
        return invoke_url

    def update_envs(self, full_function_name: str, envs: Dict) -> Dict:
        """Merge new environment variables with existing Cloud Run service environment.

        Args:
            full_function_name: Fully qualified service name
            envs: New environment variables to add/update

        Returns:
            Merged environment variables dictionary
        """
        get_req = (
            self.run_client.projects().locations().services().get(name=full_function_name)
        )  # type: ignore
        response = get_req.execute()

        existing_envs = {}
        if "template" in response and "containers" in response["template"]:
            container = response["template"]["containers"][0]
            if "env" in container:
                for e in container["env"]:
                    existing_envs[e["name"]] = e["value"]

        # Merge: new overrides old
        envs = {**existing_envs, **envs}
        return envs

    def generate_runtime_envs(self) -> Dict:
        """Return runtime environment variables for Cloud Run deployments.

        Returns:
            Runtime environment variables for Gunicorn worker configuration.
        """
        dep_config = self.config.deployment_config.container_config
        return {
            "GUNICORN_WORKERS": str(dep_config.worker_concurrency),
            "GUNICORN_THREADS": str(dep_config.worker_threads),
        }

    def is_deployed(self, func_name: str, versionId: int = -1) -> Tuple[bool, int]:
        """Check if Cloud Run service is deployed.

        Args:
            func_name: Name of the service to check
            versionId: Ignored for Cloud Run (always returns 0)

        Returns:
            Tuple of (is_deployed, 0)
        """
        service_name = func_name.replace("_", "-").lower()
        name = self.get_full_function_name(
            self.config.project_name, self.config.region, service_name
        )
        try:
            svc = self.run_client.projects().locations().services().get(name=name).execute()
            conditions = svc.get("terminalCondition", {})
            is_ready = conditions.get("type", "") == "Ready"
            return (is_ready, 0)
        except HttpError:
            return (False, -1)

    def delete_function(self, func_name: str) -> None:
        """Delete a Cloud Run service.

        Args:
            func_name: Name of the service to delete
        """
        self.logging.info(f"Deleting Cloud Run service {func_name}")

        service_name = func_name.replace("_", "-").lower()
        full_service_name = self.get_full_function_name(
            self.config.project_name, self.config.region, service_name
        )

        try:
            delete_req = (
                self.run_client.projects().locations().services().delete(name=full_service_name)
            )
            delete_req.execute()
            self.logging.info(f"Cloud Run service {func_name} deleted successfully")
        except HttpError as e:
            if e.resp.status == 404:
                self.logging.error(f"Cloud Run service {func_name} does not exist!")
            else:
                self.logging.error(f"Failed to delete Cloud Run service {func_name}: {e}")
                raise

    def download_execution_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
    ) -> None:
        """Download execution times for Cloud Run from request logs."""
        service_name = function_name.replace("_", "-").lower()
        CloudRunMetricsHelper.download_execution_metrics(
            self.logging,
            self.config.project_name,
            service_name,
            start_time,
            end_time,
            requests,
            "GCP Cloud Run",
        )

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, metrics: Dict
    ) -> None:
        """Download monitoring metrics for a Cloud Run service.

        Args:
            function_name: Name of the deployed service.
            start_time: Start timestamp for metric collection.
            end_time: End timestamp for metric collection.
            metrics: Dictionary to populate with monitoring samples.
        """
        service_name = function_name.replace("_", "-").lower()
        CloudRunMetricsHelper.download_metrics(
            self.config.project_name, service_name, start_time, end_time, metrics
        )


class CloudFunctionGen2Strategy(DeploymentStrategy):
    """Deployment strategy for Google Cloud Functions Gen2 package deployments."""

    def __init__(self, config: GCPConfig, logging_handlers: ColoredWrapper):
        """Initialize the Gen2 deployment strategy.

        Args:
            config: GCP deployment configuration.
            logging_handlers: Logging wrapper used for status reporting.
        """
        self.config = config
        self.logging = logging_handlers
        self.function_client = build("cloudfunctions", "v2", cache_discovery=False)
        self.run_client = build("run", "v2", cache_discovery=False)

    @staticmethod
    def get_full_function_name(project_name: str, location: str, func_name: str) -> str:
        """Build the fully qualified Cloud Functions Gen2 resource name.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function name.

        Returns:
            Fully qualified Cloud Functions Gen2 resource name.
        """
        return f"projects/{project_name}/locations/{location}/functions/{func_name}"

    def function_exists(self, project_name: str, location: str, func_name: str) -> Any:
        """Check whether the Cloud Functions Gen2 resource exists.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function name.

        Returns:
            True if the function exists, otherwise False.
        """
        full_resource_name = self.get_full_function_name(project_name, location, func_name)
        get_req = (
            self.function_client.projects().locations().functions().get(name=full_resource_name)
        )
        try:
            self._execute_with_retry(self.logging, get_req)
            return True
        except HttpError as e:
            if e.resp.status == 404:
                return False
            raise RuntimeError(f"Error checking function existence: {e}") from None

    def _entry_point(self, code_package: Benchmark) -> str:
        """Resolve the runtime entry point for a benchmark package.

        Args:
            code_package: Benchmark package being deployed.

        Returns:
            Entry point name expected by the deployed runtime.
        """
        return (
            "org.serverlessbench.Handler" if code_package.language == Language.JAVA else "handler"
        )

    def _runtime(self, code_package: Benchmark) -> str:
        """Resolve the Cloud Functions Gen2 runtime identifier.

        Args:
            code_package: Benchmark package being deployed.

        Returns:
            Runtime identifier string for the GCP API.
        """
        return code_package.language_name + code_package.language_version.replace(".", "")

    def _service_config(
        self, benchmark_config: BenchmarkConfig | FunctionConfig, envs: Dict
    ) -> Dict:
        """Build the Gen2 service configuration payload.

        Args:
            benchmark_config: Benchmark or function configuration with memory and timeout.
            envs: Environment variables to configure on the service.

        Returns:
            Service configuration payload for Cloud Functions Gen2.
        """
        dep_config = self.config.deployment_config.function_gen2_config
        return {
            "availableMemory": f"{benchmark_config.memory}Mi",
            "timeoutSeconds": benchmark_config.timeout,
            "environmentVariables": envs,
            "minInstanceCount": dep_config.min_instances,
            "maxInstanceCount": dep_config.max_instances,
            "availableCpu": str(dep_config.vcpus),
            "maxInstanceRequestConcurrency": dep_config.gcp_concurrency,
            "ingressSettings": "ALLOW_ALL",
            "allTrafficOnLatestRevision": True,
        }

    def _build_body(
        self,
        func_name: str,
        code_package: Benchmark,
        envs: Dict,
        storage_source: Dict,
    ) -> Dict:
        """Build the full Cloud Functions Gen2 create or patch payload.

        Args:
            func_name: Function name.
            code_package: Benchmark package being deployed.
            envs: Environment variables for the service.
            storage_source: Uploaded source archive descriptor.

        Returns:
            Full function resource payload.
        """
        return {
            "name": self.get_full_function_name(
                self.config.project_name, self.config.region, func_name
            ),
            "buildConfig": {
                "runtime": self._runtime(code_package),
                "entryPoint": self._entry_point(code_package),
                "source": {"storageSource": storage_source},
            },
            "serviceConfig": self._service_config(code_package.benchmark_config, envs),
        }

    def _generate_upload_url(self) -> Dict:
        """Request a signed upload URL for a Gen2 source archive.

        Returns:
            Upload metadata returned by the Cloud Functions Gen2 API.
        """
        parent = f"projects/{self.config.project_name}/locations/{self.config.region}"
        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .generateUploadUrl(parent=parent, body={"environment": "GEN_2"})
        )
        return self._execute_with_retry(self.logging, req)

    def _upload_zip_archive(self, package_path: str) -> Dict:
        """Upload a ZIP archive to the signed Gen2 source upload URL.

        Args:
            package_path: Path to the ZIP archive to upload.

        Returns:
            Storage source descriptor referencing the uploaded archive.
        """
        upload_info = self._generate_upload_url()
        with open(package_path, "rb") as package_fp:
            request = urllib.request.Request(
                upload_info["uploadUrl"],
                data=package_fp.read(),
                method="PUT",
                headers={"Content-Type": "application/zip"},
            )
            with urllib.request.urlopen(request) as response:
                if response.status not in (200, 201):
                    raise RuntimeError(
                        f"Upload of package archive failed with HTTP {response.status}"
                    )
        return cast(Dict, upload_info["storageSource"])

    def create(
        self,
        func_name: str,
        code_package: Benchmark,
        function_cfg: FunctionConfig,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Create a new Cloud Functions Gen2 deployment.

        Args:
            func_name: Function name to create.
            code_package: Benchmark package with code to deploy.
            function_cfg: Function configuration.
            envs: Environment variables for the function service.
            container_uri: Unused for package deployments.
        """
        if code_package.code_location is None:
            raise RuntimeError("Code location is not set for GCP deployment")

        parent = f"projects/{self.config.project_name}/locations/{self.config.region}"
        storage_source = self._upload_zip_archive(code_package.code_location)
        function_body = self._build_body(func_name, code_package, envs, storage_source)
        create_req = (
            self.function_client.projects()
            .locations()
            .functions()
            .create(
                parent=parent, functionId=func_name, body=function_body  # type: ignore[arg-type]
            )
        )
        self._operation_response = self._execute_with_retry(self.logging, create_req)
        self.logging.info(f"Function {func_name} is creating through Cloud Functions Gen2")

    def update_code(
        self,
        function: GCPFunction,
        code_package: Benchmark,
        envs: Dict,
        container_uri: str | None,
    ) -> None:
        """Update the code of an existing Cloud Functions Gen2 deployment.

        Args:
            function: Existing deployed function.
            code_package: New benchmark package to upload.
            envs: Environment variables for the updated service.
            container_uri: Unused for package deployments.
        """
        if code_package.code_location is None:
            raise RuntimeError("Code location is not set for GCP deployment")

        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )
        storage_source = self._upload_zip_archive(code_package.code_location)
        function_body = self._build_body(function.name, code_package, envs, storage_source)
        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(
                name=full_func_name,
                body=function_body,  # type: ignore[arg-type]
                updateMask="buildConfig.runtime,buildConfig.entryPoint,"
                "buildConfig.source.storageSource,serviceConfig",
            )
        )
        self._operation_response = self._execute_with_retry(self.logging, req)
        self.logging.info(f"Function {function.name} code update initiated for Gen2")

    def update_config(self, function: GCPFunction, envs: Dict) -> int:
        """Update configuration of an existing Cloud Functions Gen2 deployment.

        Args:
            function: Deployed function to update.
            envs: Full environment variable map to apply.

        Returns:
            Placeholder version value for interface compatibility.
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )
        body = {"serviceConfig": self._service_config(function.config, envs)}
        req = (
            self.function_client.projects()
            .locations()
            .functions()
            .patch(
                name=full_func_name,
                body=body,  # type: ignore[arg-type]
                updateMask="serviceConfig",
            )
        )
        self._operation_response = self._execute_with_retry(self.logging, req)
        self.wait_for_deployment(function.name)
        return 0

    def wait_for_deployment(self, func_name: str) -> None:
        """Wait for the active create or patch operation to complete.

        Args:
            func_name: Function name being deployed.
        """
        if not hasattr(self, "_operation_response"):
            raise RuntimeError("No operation to wait for - create/update not called")

        op_name = self._operation_response["name"]
        begin = time.time()
        while True:
            op_req = self.function_client.projects().locations().operations().get(name=op_name)
            op_res = self._execute_with_retry(self.logging, op_req)
            if op_res.get("done"):
                if "error" in op_res:
                    raise RuntimeError(f"Cloud Functions Gen2 deployment failed: {op_res['error']}")
                break
            if time.time() - begin > 600:
                raise RuntimeError(f"Timeout waiting for Cloud Functions Gen2 operation {op_name}")
            time.sleep(3)

        self._wait_for_active_status(func_name)
        delattr(self, "_operation_response")

    def _wait_for_active_status(self, func_name: str, timeout: int = 300) -> None:
        """Poll the Gen2 function until it reaches the ACTIVE state.

        Args:
            func_name: Function name to monitor.
            timeout: Maximum wait time in seconds.
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        begin = time.time()
        last_state: Optional[str] = None
        while True:
            req = self.function_client.projects().locations().functions().get(name=full_func_name)
            func_details = self._execute_with_retry(self.logging, req)
            state = func_details.get("state")
            if state != last_state:
                self.logging.info(f"Function {func_name} state: {state}")
                last_state = cast(Optional[str], state)

            if state == "ACTIVE" and func_details.get("serviceConfig", {}).get("uri"):
                return
            if state in ("FAILED", "UNKNOWN"):
                raise RuntimeError(
                    f"Function {func_name} deployment failed with state {state}: "
                    f"{func_details.get('stateMessages', [])}"
                )
            if time.time() - begin > timeout:
                raise RuntimeError(
                    "Timeout waiting for function "
                    f"{func_name} to become ACTIVE. Last state: {state}"
                )
            time.sleep(3)

    def allow_public_access(self, project_name: str, location: str, func_name: str) -> None:
        """Grant public invocation access to the underlying Cloud Run service.

        Args:
            project_name: GCP project ID.
            location: GCP region/location.
            func_name: Function name whose backing service should be public.
        """
        service_name = func_name.replace("_", "-").lower()
        full_service_name = f"projects/{project_name}/locations/{location}/services/{service_name}"
        req = (
            self.run_client.projects()
            .locations()
            .services()
            .setIamPolicy(
                resource=full_service_name,
                body={
                    "policy": {
                        "bindings": [
                            {
                                "role": "roles/run.invoker",
                                "members": ["allUsers"],
                            }
                        ]
                    }
                },
            )
        )
        self._execute_with_retry(self.logging, req)

    def create_trigger(self, func_name: str) -> str:
        """Return the HTTPS trigger URL for a Gen2 function.

        Args:
            func_name: Function name.

        Returns:
            Public invoke URL for the function.
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        req = self.function_client.projects().locations().functions().get(name=full_func_name)
        func_details = self._execute_with_retry(self.logging, req)
        invoke_url = func_details["serviceConfig"]["uri"]
        self.logging.info(f"Function {func_name} - HTTP trigger URL: {invoke_url}")
        return invoke_url

    def update_envs(self, full_function_name: str, envs: Dict) -> Dict:
        """Merge new environment variables with existing Gen2 service variables.

        Args:
            full_function_name: Fully qualified function name.
            envs: New environment variables to add or override.

        Returns:
            Merged environment variables dictionary.
        """
        req = self.function_client.projects().locations().functions().get(name=full_function_name)
        response = self._execute_with_retry(self.logging, req)
        existing_envs = response.get("serviceConfig", {}).get("environmentVariables", {})
        return {**existing_envs, **envs}

    def generate_runtime_envs(self) -> Dict:
        """Return runtime environment overrides for Gen2 package deployments.

        Returns:
            Environment variables controlling Gunicorn worker settings.
        """
        dep_config = self.config.deployment_config.function_gen2_config
        return {
            "GUNICORN_WORKERS": str(dep_config.worker_concurrency),
            "GUNICORN_THREADS": str(dep_config.worker_threads),
        }

    def is_deployed(self, func_name: str, versionId: int = -1) -> Tuple[bool, int]:
        """Check whether a Gen2 function is deployed and ready.

        Args:
            func_name: Function name to inspect.
            versionId: Unused for Gen2 deployments.

        Returns:
            Tuple of readiness flag and placeholder version value.
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        try:
            req = self.function_client.projects().locations().functions().get(name=full_func_name)
            func_details = self._execute_with_retry(self.logging, req)
            is_ready = func_details.get("state") == "ACTIVE" and "uri" in func_details.get(
                "serviceConfig", {}
            )
            return (is_ready, 0)
        except HttpError:
            return (False, -1)

    def delete_function(self, func_name: str) -> None:
        """Delete a Cloud Functions Gen2 deployment.

        Args:
            func_name: Function name to delete.
        """
        full_func_name = self.get_full_function_name(
            self.config.project_name, self.config.region, func_name
        )
        try:
            req = (
                self.function_client.projects().locations().functions().delete(name=full_func_name)
            )
            self._execute_with_retry(self.logging, req)
        except HttpError as e:
            if e.resp.status != 404:
                raise

    def download_execution_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
    ) -> None:
        """Download execution timings for a Gen2 function from request logs.

        Args:
            function_name: Function name whose backing service is queried.
            start_time: Start timestamp for log collection.
            end_time: End timestamp for log collection.
            requests: Invocation results keyed by request ID.
        """
        service_name = function_name.replace("_", "-").lower()
        CloudRunMetricsHelper.download_execution_metrics(
            self.logging,
            self.config.project_name,
            service_name,
            start_time,
            end_time,
            requests,
            "GCP Cloud Functions Gen2",
        )

    def download_metrics(
        self, function_name: str, start_time: int, end_time: int, metrics: Dict
    ) -> None:
        """Download monitoring metrics for a Gen2 function.

        Args:
            function_name: Function name whose backing service is queried.
            start_time: Start timestamp for metric collection.
            end_time: End timestamp for metric collection.
            metrics: Dictionary to populate with monitoring samples.
        """
        service_name = function_name.replace("_", "-").lower()
        CloudRunMetricsHelper.download_metrics(
            self.config.project_name, service_name, start_time, end_time, metrics
        )


class GCP(System):
    """Google Cloud Platform serverless system implementation.

    Provides complete integration with Google Cloud Functions including deployment,
    monitoring, logging, and resource management. Handles code packaging, function
    lifecycle management, trigger creation, and performance metrics collection.

    Attributes:
        _config: GCP-specific configuration including credentials and region
        function_client: Google Cloud Functions API client
        cold_start_counter: Counter for enforcing cold starts in benchmarking
        logging_handlers: Logging configuration for status reporting
    """

    def __init__(
        self,
        system_config: SeBSConfig,
        config: GCPConfig,
        cache_client: Cache,
        docker_client: docker.client.DockerClient,
        logging_handlers: LoggingHandlers,
    ) -> None:
        """Initialize GCP serverless system.

        Args:
            system_config: General SeBS system configuration
            config: GCP-specific configuration with credentials and settings
            cache_client: Cache instance for storing function and resource state
            docker_client: Docker client for container operations (if needed)
            logging_handlers: Logging configuration for status reporting
        """
        super().__init__(
            system_config,
            cache_client,
            docker_client,
            GCPSystemResources(
                system_config, config, cache_client, docker_client, logging_handlers
            ),
        )
        self._config = config
        self.logging_handlers = logging_handlers

    @property
    def config(self) -> GCPConfig:
        """Get the GCP configuration instance.

        Returns:
            GCP configuration with credentials and region settings
        """
        return self._config

    @staticmethod
    def name() -> str:
        """Get the platform name identifier.

        Returns:
            Platform name string 'gcp'
        """
        return "gcp"

    @staticmethod
    def typename() -> str:
        """Get the platform type name for display.

        Returns:
            Platform type string 'GCP'
        """
        return "GCP"

    @staticmethod
    def function_type() -> "Type[Function]":
        """Get the function class type for this platform.

        Returns:
            GCPFunction class type
        """
        return GCPFunction

    def initialize(
        self,
        config: Dict[str, str] = {},
        resource_prefix: Optional[str] = None,
        quiet: bool = False,
    ) -> None:
        """Initialize the GCP system for function deployment and management.

        Sets up the Cloud Functions API client and initializes system resources
        including storage buckets and other required infrastructure.
        After this call, the GCP system should be ready to allocate functions,
        manage storage, and invoke functions.

        Args:
            config: Additional system-specific configuration parameters
            resource_prefix: Optional prefix for resource naming to avoid conflicts
        """

        self.initialize_resources(select_prefix=resource_prefix, quiet=quiet)

        storage = cast(GCPStorage, self._system_resources.get_storage())

        # Initialize deployment strategies
        self.cloud_function_gen1_strategy = CloudFunctionGen1Strategy(
            storage, self._config, self.logging
        )
        self.cloud_function_gen2_strategy = CloudFunctionGen2Strategy(self._config, self.logging)
        self.run_container_strategy = RunContainerStrategy(self._config, self.logging)

        self.gcr_client = GCRContainer(self.system_config, self.config, self.docker_client)

    @property
    def container_client(self) -> GCRContainer | None:
        """Get the GCP-specific container manager that uses Artifact Registry.

        Returns:
            Container manager instance.
        """
        return self.gcr_client

    def get_function_client(self):
        """Get the Cloud Functions v1 API client.

        Returns:
            Google Cloud Functions v1 API client
        """
        return self.cloud_function_gen1_strategy.function_client

    def get_run_client(self):
        """Get the Cloud Run v2 API client.

        Returns:
            Google Cloud Run v2 API client
        """
        return self.run_container_strategy.run_client

    def _resolve_deployment_type(self, container_deployment: bool) -> FunctionDeploymentType:
        """Resolve the effective GCP deployment type for a benchmark.

        Args:
            container_deployment: Whether the experiment selected container mode.

        Returns:
            Effective deployment type after applying GCP-local package settings.
        """
        return FunctionDeploymentType.resolve(
            container_deployment, self.config.deployment_config.package_deployment_type
        )

    def system_variant_suffix(self, container_deployment: bool) -> Optional[str]:
        """Return a provider-local system variant suffix for GCP package variants.

        Args:
            container_deployment: Whether the benchmark uses container deployment.

        Returns:
            Short suffix for GCP package variants, otherwise ``None``.
        """
        deployment_type = self._resolve_deployment_type(container_deployment)
        if deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
            return "gen1"
        if deployment_type == FunctionDeploymentType.FUNCTION_GEN2:
            return "gen2"
        return None

    def _strategy_for_deployment_type(self, deployment_type: FunctionDeploymentType):
        """Return the deployment strategy for a resolved GCP deployment type.

        Args:
            deployment_type: Effective deployment type to dispatch.

        Returns:
            Deployment strategy object handling the requested mode.
        """
        if deployment_type == FunctionDeploymentType.CONTAINER:
            return self.run_container_strategy
        if deployment_type == FunctionDeploymentType.FUNCTION_GEN2:
            return self.cloud_function_gen2_strategy
        return self.cloud_function_gen1_strategy

    def _get_deployment_config(
        self, deployment_type: FunctionDeploymentType
    ) -> Union[GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig]:
        """Return the deployment config that matches the requested deployment type.

        Args:
            deployment_type: Deployment type to resolve.

        Returns:
            Deployment configuration object for the requested type.
        """
        if deployment_type.is_container:
            return self.config.deployment_config.container_config
        else:
            if deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
                return self.config.deployment_config.function_gen1_config
            else:
                return self.config.deployment_config.function_gen2_config

    def is_configuration_changed(self, cached_function: Function, benchmark: Benchmark) -> bool:
        """
        Override the default implementation.

        In addition to checking for timeout and language runtime - the shared config
        - we also check if the GCP-specific config has changed.

        Args:
            cached_function: Previously cached function configuration
            benchmark: Current benchmark configuration to compare against

        Returns:
            True if configuration has changed and function needs updating
        """
        changed = super().is_configuration_changed(cached_function, benchmark)

        # Check if deployment config has changed
        cached_function = cast(GCPFunction, cached_function)
        expected_deployment_type = self._resolve_deployment_type(benchmark.container_deployment)
        if cached_function.deployment_type != expected_deployment_type:
            self.logging.info(
                f"Deployment type has changed for {cached_function.name}: "
                f"cached function uses {cached_function.deployment_type.value}, "
                f"requested deployment is {expected_deployment_type.value}."
            )
            changed = True

        current_dep_config = self._get_deployment_config(cached_function.deployment_type)

        if cached_function.deployment_config != current_dep_config:
            self.logging.info(
                f"Deployment config has changed for {cached_function.name}, "
                "will update configuration."
            )
            changed = True

        return changed

    def can_reuse_cached_function(
        self, cached_function: Function, benchmark: Benchmark
    ) -> Optional[str]:
        """Check whether a cached GCP function matches the requested deployment mode.

        Args:
            cached_function: Cached function selected from SeBS cache.
            benchmark: Benchmark requesting the function.

        Returns:
            str: if the cached function does not fit the requested deployment type.
        """
        gcp_function = cast(GCPFunction, cached_function)
        expected_deployment_type = self._resolve_deployment_type(benchmark.container_deployment)

        if gcp_function.deployment_type != expected_deployment_type:
            return (
                f"cached deployment type {gcp_function.deployment_type.value} "
                f"does not match requested deployment type {expected_deployment_type.value}"
            )

        return None

    def default_function_name(
        self, code_package: Benchmark, resources: Optional[Resources] = None
    ) -> str:
        """Generate a default function name for the given benchmark.

        Creates a standardized function name using resource ID, benchmark name,
        language, and version information. Formats the name according to GCP
        Cloud Functions naming requirements.

        Args:
            code_package: Benchmark package containing metadata
            resources: Optional resource configuration for ID generation

        Returns:
            Formatted function name suitable for GCP Cloud Functions
        """
        # Create function name
        resource_id = resources.resources_id if resources else self.config.resources.resources_id
        # Extract benchmark number (e.g., "110" from "110.dynamic-html")
        benchmark_number = code_package.benchmark.split(".")[0]
        func_name = "sebs-{}-{}-{}-{}-{}".format(
            resource_id,
            benchmark_number,
            code_package.language_name,
            code_package.language_version,
            code_package.architecture,
        )
        deployment_type = self._resolve_deployment_type(code_package.container_deployment)
        if deployment_type == FunctionDeploymentType.CONTAINER:
            func_name = f"{func_name}-docker"
        elif deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
            func_name = f"{func_name}-gen1"
        elif deployment_type == FunctionDeploymentType.FUNCTION_GEN2:
            func_name = f"{func_name}-gen2"
        return (
            GCP.format_function_name(func_name)
            if deployment_type != FunctionDeploymentType.CONTAINER
            else func_name.replace(".", "-")
        )

    @staticmethod
    def format_function_name(func_name: str) -> str:
        """Format function name according to GCP Cloud Functions requirements.

        Converts function names to comply with GCP naming rules by replacing
        hyphens and dots with underscores. GCP functions must begin with a letter
        and can only contain letters, numbers, and underscores.

        Args:
            func_name: Raw function name to format

        Returns:
            GCP-compliant function name
        """
        # GCP functions must begin with a letter
        # however, we now add by default `sebs` in the beginning
        func_name = func_name.replace("-", "_")
        func_name = func_name.replace(".", "_")
        return func_name

    def package_code(
        self,
        directory: str,
        language: Language,
        language_version: str,
        architecture: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]:
        """Package benchmark code for GCP Cloud Functions deployment.

        Transforms the benchmark code directory structure to meet GCP Cloud Functions
        requirements. Creates a zip archive with the appropriate handler file naming
        and directory structure for the specified language runtime.

        The packaging process:
        1. Creates a 'function' subdirectory for benchmark sources
        2. Renames handler files to GCP-required names (handler.py -> main.py)
        3. Creates a zip archive for deployment
        4. Restores original file structure

        Args:
            directory: Path to the benchmark code directory
            language: Programming language (python, nodejs)
            language_version: Language version (e.g., '3.8', '14')
            architecture: Target architecture (x86_64, arm64)
            benchmark: Benchmark name for archive naming
            is_cached: Whether this package is from cache

        Returns:
            Tuple of (archive_path, archive_size_bytes)
        """

        if language == Language.CPP:
            raise NotImplementedError("C++ packaging is not supported on GCP!")

        """
            While for Java we produce an archive alread (JAR),
            we need to pack in a zip file as their build sysstem will unzip it
            and complain that it finds classes, and not a JAR.
        """
        CONFIG_FILES = {
            Language.PYTHON: ["handler.py", ".python_packages"],
            Language.NODEJS: ["handler.js", "node_modules"],
            Language.JAVA: ["function.jar"],
        }
        HANDLER = {
            Language.PYTHON: ("handler.py", "main.py"),
            Language.NODEJS: ("handler.js", "index.js"),
        }
        package_config = CONFIG_FILES[language]
        function_dir = os.path.join(directory, "function")
        os.makedirs(function_dir)
        for file in os.listdir(directory):
            if file not in package_config:
                file = os.path.join(directory, file)
                shutil.move(file, function_dir)

        # rename handler function.py since in gcp it has to be caled main.py
        old_path, new_path = None, None
        if language in HANDLER:
            old_name, new_name = HANDLER[language]
            old_path = os.path.join(directory, old_name)
            new_path = os.path.join(directory, new_name)
            shutil.move(old_path, new_path)

        """
            zip the whole directory (the zip-file gets uploaded to gcp later)

            Note that the function GCP.recursive_zip is slower than the use of e.g.
            `utils.execute("zip -qu -r9 {}.zip * .".format(benchmark), shell=True)`
            or `shutil.make_archive(benchmark_archive, direcory, directory)`
            But both of the two alternatives need a change of directory
            (shutil.make_archive does the directory change internaly)
            which leads to a "race condition" when running several benchmarks
            in parallel, since a change of the current directory is NOT Thread specfic.
        """
        benchmark_archive = "{}.zip".format(os.path.join(directory, benchmark))
        GCP.recursive_zip(directory, benchmark_archive)
        logging.info("Created {} archive".format(benchmark_archive))

        bytes_size = os.path.getsize(benchmark_archive)
        mbytes = bytes_size / 1024.0 / 1024.0
        logging.info("Zip archive size {:2f} MB".format(mbytes))

        # rename the main.py back to handler.py
        if new_path is not None and old_path is not None:
            shutil.move(new_path, old_path)

        return (
            os.path.join(directory, "{}.zip".format(benchmark)),
            bytes_size,
        )

    def create_function(
        self,
        code_package: Benchmark,
        func_name: str,
        container_deployment: bool,
        container_uri: str | None,
    ) -> GCPFunction:
        """Create a new GCP Cloud Function or update existing one.

        Deploys a benchmark as a Cloud Function, handling code upload to Cloud Storage,
        function creation with proper configuration, and IAM policy setup for
        unauthenticated invocations (HTTP triggers).
        If the function already exists, updates it instead.

        Args:
            code_package: Benchmark package with code and configuration
            func_name: Name for the Cloud Function
            container_deployment: Whether to use container deployment (unsupported)
            container_uri: Container image URI (unused for GCP)

        Returns:
            GCPFunction instance representing the deployed function

        Raises:
            NotImplementedError: If container_deployment is True
            RuntimeError: If function creation or IAM configuration fails
        """

        benchmark = code_package.benchmark
        location = self.config.region
        project_name = self.config.project_name
        function_cfg = FunctionConfig.from_benchmark(code_package)
        architecture = function_cfg.architecture.value
        code_bucket: Optional[str] = None
        dep_config: Union[GCPFunctionGen1Config, GCPFunctionGen2Config, GCPContainerConfig]

        if architecture == "arm64":
            raise RuntimeError("GCP does not support arm64 deployments")

        deployment_type = self._resolve_deployment_type(container_deployment)
        strategy = self._strategy_for_deployment_type(deployment_type)

        # Check if function/service already exists
        function_exists = strategy.function_exists(project_name, location, func_name)

        dep_config = self._get_deployment_config(deployment_type)
        if not function_exists:
            # Create new function/service
            envs = {
                **self._generate_function_envs(code_package),
                **strategy.generate_runtime_envs(),
            }

            # Get code bucket for non-container deployments

            strategy.create(func_name, code_package, function_cfg, envs, container_uri)
            strategy.wait_for_deployment(func_name)
            strategy.allow_public_access(project_name, location, func_name)

            if not deployment_type.is_container:
                storage_client = self._system_resources.get_storage()
                code_bucket = storage_client.get_bucket(Resources.StorageBucketType.DEPLOYMENT)
                function = GCPFunction(
                    func_name,
                    benchmark,
                    code_package.hash,
                    function_cfg,
                    deployment_type,
                    dep_config,
                    code_bucket,
                    None,
                )
            else:
                function = GCPFunction(
                    func_name,
                    benchmark,
                    code_package.hash,
                    function_cfg,
                    deployment_type,
                    dep_config,
                    None,
                    container_uri,
                )
        else:
            # Function/service exists, update it
            self.logging.info("Function {} exists on GCP, update the instance.".format(func_name))

            function = GCPFunction(
                name=func_name,
                benchmark=benchmark,
                code_package_hash=code_package.hash,
                cfg=function_cfg,
                deployment_type=deployment_type,
                bucket=code_bucket,
                deployment_config=dep_config,
                container_uri=container_uri,
            )

            strategy.allow_public_access(project_name, location, func_name)
            self.update_function(function, code_package, container_deployment, container_uri)

        # Add LibraryTrigger to a new function
        # Not supported on containers
        if deployment_type == FunctionDeploymentType.FUNCTION_GEN1:
            from sebs.gcp.triggers import LibraryTrigger

            trigger = LibraryTrigger(func_name, self, function.deployment_type)
            trigger.logging_handlers = self.logging_handlers
            function.add_trigger(trigger)

        return function

    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
        """Create a trigger for the given function.

        Creates HTTP triggers for Cloud Functions, waiting for function deployment
        to complete before extracting the trigger URL.
        Only HTTP triggers are supported here; Library triggers are added by
        default during function creation.

        Args:
            function: Function instance to create trigger for
            trigger_type: Type of trigger to create (only HTTP supported)

        Returns:
            Created trigger instance with URL and configuration

        Raises:
            RuntimeError: If trigger type is not supported
        """
        from sebs.gcp.triggers import HTTPTrigger
        from sebs.gcp.function import GCPFunction

        if trigger_type == Trigger.TriggerType.HTTP:
            gcp_function = cast(GCPFunction, function)
            self.logging.info(f"Function {function.name} - waiting for deployment...")

            # Select deployment strategy
            strategy = self._strategy_for_deployment_type(gcp_function.deployment_type)

            # Get trigger URL from strategy
            invoke_url = strategy.create_trigger(function.name)

            trigger = HTTPTrigger(invoke_url)
        else:
            raise RuntimeError("Not supported!")

        trigger.logging_handlers = self.logging_handlers
        function.add_trigger(trigger)
        self.cache_client.update_function(function)
        return trigger

    def cached_function(self, function: Function) -> None:
        """Configure a cached function instance for use.

        Sets up library triggers for functions loaded from cache, ensuring
        they have the proper deployment client and logging configuration.

        Args:
            function: Cached function instance to configure
        """

        from sebs.faas.function import Trigger
        from sebs.gcp.triggers import LibraryTrigger

        func = cast(GCPFunction, function)

        for trigger in function.triggers(Trigger.TriggerType.LIBRARY):
            gcp_trigger = cast(LibraryTrigger, trigger)
            gcp_trigger.deployment_type = func.deployment_type
            gcp_trigger.logging_handlers = self.logging_handlers
            gcp_trigger.deployment_client = self

    def update_function(
        self,
        function: Function,
        code_package: Benchmark,
        container_deployment: bool,
        container_uri: str | None,
    ) -> None:
        """Update an existing Cloud Function with new code and configuration.

        Uploads new code package to Cloud Storage and patches the existing function
        with updated runtime, memory, timeout, and environment variables. Waits
        for deployment to complete before returning.

        Args:
            function: Existing function instance to update
            code_package: New benchmark package with updated code
            container_deployment: Whether to use container deployment (unsupported)
            container_uri: Container image URI (unused)

        Raises:
            NotImplementedError: If container_deployment is True
            RuntimeError: If function update fails after maximum retries
        """

        function = cast(GCPFunction, function)

        # Select deployment strategy
        strategy = self._strategy_for_deployment_type(function.deployment_type)

        # Generate environment variables
        envs = {
            **self._generate_function_envs(code_package),
            **strategy.generate_runtime_envs(),
        }

        # Update code using strategy
        strategy.update_code(function, code_package, envs, container_uri)
        if container_deployment:
            function.set_container_uri(container_uri)
        strategy.wait_for_deployment(function.name)

    def _generate_function_envs(self, code_package: Benchmark) -> Dict:
        """Generate environment variables for function based on benchmark requirements.

        Creates environment variables needed by the benchmark, such as NoSQL
        database connection information.

        Args:
            code_package: Benchmark package with module requirements

        Returns:
            Dictionary of environment variables for the function
        """

        envs = {}
        if code_package.uses_nosql:

            db = (
                cast(GCPSystemResources, self._system_resources)
                .get_nosql_storage()
                .benchmark_database(code_package.benchmark)
            )
            envs["NOSQL_STORAGE_DATABASE"] = db

        return envs

    def update_function_configuration(
        self, function: Function, code_package: Benchmark, env_variables: Dict = {}
    ) -> int:
        """Update function configuration including memory, timeout, and environment.

        Updates the Cloud Function's memory allocation, timeout, and environment
        variables without changing the code. Waits for deployment to complete.

        Args:
            function: Function instance to update
            code_package: Benchmark package with configuration requirements
            env_variables: Additional environment variables to set
            container_uri: Container image URI (for container deployments)

        Returns:
            Version ID of the updated function

        Raises:
            RuntimeError: If configuration update fails after maximum retries
        """

        assert code_package.has_input_processed

        function = cast(GCPFunction, function)

        # Select deployment strategy
        strategy = self._strategy_for_deployment_type(function.deployment_type)

        # Get full resource name for env merging
        full_func_name = strategy.get_full_function_name(
            self.config.project_name, self.config.region, function.name
        )

        # Prepare environment variables
        envs = {
            **self._generate_function_envs(code_package),
            **strategy.generate_runtime_envs(),
        }
        envs = {**envs, **env_variables}

        # GCP might overwrite existing variables
        # If we modify them, we need to first read existing ones and append.
        if len(envs) > 0:
            envs = strategy.update_envs(full_func_name, envs)

        # Update configuration using strategy
        res = strategy.update_config(function, envs)

        current_dep_config = self._get_deployment_config(function.deployment_type)
        function._deployment_config = current_dep_config

        return res

    def delete_function(self, func_name: str, function: Dict) -> None:
        """Delete a Google Cloud Function or Cloud Run service.

        Args:
            func_name: Name of the function/service to delete
        """
        # Select deployment strategy based on function name
        # v1 functions don't allow hyphens, new functions don't allow underscores
        gcp_function = GCPFunction.deserialize(function)
        strategy = self._strategy_for_deployment_type(gcp_function.deployment_type)

        strategy.delete_function(func_name)

    def shutdown(self) -> None:
        """Shutdown the GCP system and clean up resources.

        Performs cleanup of system resources and calls parent shutdown method.
        """
        cast(GCPSystemResources, self._system_resources).shutdown()
        super().shutdown()

    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict,
        metrics: Dict,
    ) -> None:
        """Download execution metrics and logs from GCP monitoring services.

        Retrieves function execution times from Cloud Logging and performance
        metrics from Cloud Monitoring. Processes logs to extract execution times
        and collects metrics like memory usage and network egress.

        Args:
            function_name: Name of the function to collect metrics for
            start_time: Start timestamp for metric collection (Unix timestamp)
            end_time: End timestamp for metric collection (Unix timestamp)
            requests: Dictionary of requests keyed by execution ID
            metrics: Dictionary to populate with collected metrics
        """

        functions = self.cache_client.get_all_functions(self.name())
        if function_name not in functions:
            raise RuntimeError(f"Function {function_name} not found in cache!")

        function = GCPFunction.deserialize(functions[function_name])

        strategy = self._strategy_for_deployment_type(function.deployment_type)
        strategy.download_execution_metrics(function_name, start_time, end_time, requests)

        strategy.download_metrics(function_name, start_time, end_time, metrics)

    def _enforce_cold_start(self, function: Function, code_package: Benchmark) -> int:
        """Force a cold start by updating function configuration.

        Triggers a cold start by updating the function's environment variables
        with a unique counter value, forcing GCP to create a new instance.

        Args:
            function: Function instance to enforce cold start on
            code_package: Benchmark package for configuration

        Returns:
            Version ID of the updated function
        """

        self.cold_start_counter += 1
        new_version = self.update_function_configuration(
            function, code_package, {"cold_start": str(self.cold_start_counter)}
        )

        return new_version

    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark) -> None:
        """Enforce cold starts for multiple functions simultaneously.

        Updates all provided functions to force cold starts and waits for
        all deployments to complete before returning.

        Args:
            functions: List of functions to enforce cold starts on
            code_package: Benchmark package for configuration
        """

        new_versions = []
        for func in functions:
            new_versions.append((self._enforce_cold_start(func, code_package), func))
            self.cold_start_counter -= 1

        # verify deployment
        undeployed_functions = []
        deployment_done = False
        while not deployment_done:
            for versionId, func in new_versions:
                is_deployed, last_version = self.is_deployed(func, versionId)
                if not is_deployed:
                    undeployed_functions.append((versionId, func))
            deployed = len(new_versions) - len(undeployed_functions)
            self.logging.info(f"Redeployed {deployed} out of {len(new_versions)}")
            if deployed == len(new_versions):
                deployment_done = True
                break
            time.sleep(5)
            new_versions = undeployed_functions
            undeployed_functions = []

        self.cold_start_counter += 1

    def get_functions(self, code_package: Benchmark, function_names: List[str]) -> List["Function"]:
        """Retrieve multiple function instances and ensure they are deployed.

        Gets function instances for the provided names and waits for all
        functions to be in ACTIVE deployment state.

        Args:
            code_package: Benchmark package for function creation
            function_names: List of function names to retrieve

        Returns:
            List of deployed function instances
        """

        functions: List["Function"] = []
        undeployed_functions_before = []
        for func_name in function_names:
            func = self.get_function(code_package, func_name)
            functions.append(func)
            undeployed_functions_before.append(func)

        # verify deployment
        undeployed_functions = []
        deployment_done = False
        while not deployment_done:
            for func in undeployed_functions_before:
                is_deployed, last_version = self.is_deployed(func)
                if not is_deployed:
                    undeployed_functions.append(func)
            deployed = len(undeployed_functions_before) - len(undeployed_functions)
            self.logging.info(f"Deployed {deployed} out of {len(undeployed_functions_before)}")
            if deployed == len(undeployed_functions_before):
                deployment_done = True
                break
            time.sleep(5)
            undeployed_functions_before = undeployed_functions
            undeployed_functions = []
            self.logging.info(f"Waiting on {undeployed_functions_before}")

        return functions

    def is_deployed(self, function: Function, versionId: int = -1) -> Tuple[bool, int]:
        """Check if a function is deployed and optionally verify its version.
        Args:
            func_name: Name of the function to check
            versionId: Optional specific version ID to verify (-1 to check any)

        Returns:
            Tuple of (is_deployed, current_version_id)
        """
        # Select deployment strategy based on function name
        # v1 functions don't allow hyphens, new functions don't allow underscores
        gcp_function = cast(GCPFunction, function)
        strategy = self._strategy_for_deployment_type(gcp_function.deployment_type)

        return strategy.is_deployed(function.name, versionId)

    @staticmethod
    def helper_zip(base_directory: str, path: str, archive: zipfile.ZipFile) -> None:
        """Recursively add files and directories to a zip archive.

        Helper method for recursive_zip that handles directory traversal
        and adds files with relative paths to the archive.

        Args:
            base_directory: Base directory path for relative path calculation
            path: Current path being processed (file or directory)
            archive: ZipFile object to add files to
        """
        paths = os.listdir(path)
        for p in paths:
            directory = os.path.join(path, p)
            if os.path.isdir(directory):
                GCP.helper_zip(base_directory, directory, archive)
            else:
                if directory != archive.filename:  # prevent form including itself
                    archive.write(directory, os.path.relpath(directory, base_directory))

    @staticmethod
    def recursive_zip(directory: str, archname: str) -> bool:
        """Create a zip archive of a directory with relative paths.

        Creates a compressed zip archive of the specified directory, preserving
        the relative directory structure. Uses maximum compression level.

        Args:
            directory: Absolute path to the directory to be zipped
            archname: Path where the zip file should be created

        Returns:
            True if archiving was successful
        """
        archive = zipfile.ZipFile(archname, "w", zipfile.ZIP_DEFLATED, compresslevel=9)
        if os.path.isdir(directory):
            GCP.helper_zip(directory, directory, archive)
        else:
            # if the passed directory is actually a file we just add the file to the zip archive
            _, name = os.path.split(directory)
            archive.write(directory, name)
        archive.close()
        return True

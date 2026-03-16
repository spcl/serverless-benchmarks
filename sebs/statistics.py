# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Statistical analysis utilities for benchmark experiments.

This module provides functions for computing basic statistics and confidence
intervals on benchmark experiment results. It includes both parametric
(Student's t-distribution) and non-parametric (Le Boudec) methods for
computing confidence intervals.
"""

import copy
import math
import logging
from typing import Dict, List, Tuple
from collections import namedtuple

import numpy as np
import scipy.stats as st

# Named tuple for basic statistics results
from sebs.experiments.result import Result as ExperimentResult

BasicStats = namedtuple("BasicStats", "mean median std cv")


def basic_stats(times: List[float]) -> BasicStats:
    """Compute basic statistics for a list of measurement times.

    This function computes the mean, median, standard deviation, and
    coefficient of variation for a list of measurement times.

    Args:
        times: List of measurement times

    Returns:
        A BasicStats named tuple with the computed statistics
    """
    mean = np.mean(times)
    median = np.median(times)
    std = np.std(times)
    cv = std / mean * 100  # Coefficient of variation as percentage
    return BasicStats(mean, median, std, cv)


def ci_tstudents(alpha: float, times: List[float]) -> Tuple[float, float]:
    """Compute parametric confidence interval using Student's t-distribution.

    This is a parametric method that assumes the data follows a normal distribution.

    Args:
        alpha: Confidence level (e.g., 0.95 for 95% confidence)
        times: List of measurement times

    Returns:
        A tuple (lower, upper) representing the confidence interval
    """
    mean = np.mean(times)
    return st.t.interval(alpha, len(times) - 1, loc=mean, scale=st.sem(times))


def ci_le_boudec(alpha: float, times: List[float]) -> Tuple[float, float]:
    """Compute non-parametric confidence interval using Le Boudec's method.

    It requires a sufficient number of samples but it is a non-parametric
    method that does not assume that data follows the normal distribution.

    Reference:
        J.-Y. Le Boudec, "Performance Evaluation of Computer and
        Communication Systems", 2010.

    Args:
        alpha: Confidence level (e.g., 0.95 for 95% confidence)
        times: List of measurement times

    Returns:
        A tuple (lower, upper) representing the confidence interval

    Raises:
        AssertionError: If an unsupported confidence level is provided
    """
    sorted_times = sorted(times)
    n = len(times)

    # Z-values for common confidence levels
    # z(alpha/2) for two-sided interval
    z_value = {0.95: 1.96, 0.99: 2.576}.get(alpha)
    assert z_value, f"Unsupported confidence level: {alpha}"

    # Calculate positions in the sorted array
    low_pos = math.floor((n - z_value * math.sqrt(n)) / 2)
    high_pos = math.ceil(1 + (n + z_value * math.sqrt(n)) / 2)

    return (sorted_times[low_pos], sorted_times[high_pos])


def print_stats(logger: logging.Logger, experiments: ExperimentResult):
    """Print statistics of a selected experiment result.
    Used by the main CLI driver for pretty printing.

    Args:
        logger: Logger to user
        experiments: Experiment to process
    """
    for func in experiments.functions():
        logger.info(f"Processing function {func}")

        warm_times: Dict[str, list] = {
            "provider_exec": [],
            "function_exec": [],
            "client_exec": [],
            "compute": [],
            "download": [],
            "upload": [],
        }
        cold_times = {"init": [], **copy.deepcopy(warm_times)}

        for invoc in experiments.invocations(func).values():

            dst = warm_times
            if invoc.stats.cold_start:
                dst = cold_times
                if invoc.provider_times.initialization != 0:
                    dst["init"].append(invoc.provider_times.initialization)

            if invoc.provider_times.execution != 0:
                dst["provider_exec"].append(invoc.provider_times.execution)
            dst["function_exec"].append(invoc.times.benchmark)
            dst["client_exec"].append(invoc.times.client)

            if "measurement" not in invoc.output["result"]:
                continue

            measurements = invoc.output["result"]["measurement"]

            for key, result in (
                ("compute_time", "compute"),
                ("upload_time", "upload"),
                ("download_time", "download"),
            ):
                if key in measurements:
                    dst[result].append(measurements[key])

        for name_type, times in (("cold", cold_times), ("warm", warm_times)):
            logger.info(f"Processing {len(times['client_exec'])} results of {name_type} type.")

            logger.info("\tCloud provider measurements")

            for key in ("init", "provider_exec"):

                if key == "init" and name_type == "warm":
                    continue

                if len(times[key]) == 0:
                    continue

                mean, median, std, cv = basic_stats(times[key])
                logger.info(
                    f"\t\tMeasurement type {key}, mean {mean}, median {median}, std {std}, cv {cv}."
                )

            logger.info("\tIntra-function measurements")

            for key in ("function_exec", "compute", "upload", "download"):

                if len(times[key]) == 0:
                    continue

                mean, median, std, cv = basic_stats(times[key])
                logger.info(
                    f"\t\tMeasurement type {key}, mean {mean}, median {median}, std {std}, cv {cv}."
                )

            logger.info("\tClient measurements")

            for key in ("client_exec",):

                if len(times[key]) == 0:
                    continue

                mean, median, std, cv = basic_stats(times[key])
                logger.info(
                    f"\t\tMeasurement type {key}, mean {mean}, median {median}, std {std}, cv {cv}."
                )

"""Statistical analysis utilities for benchmark experiments.

This module provides functions for computing basic statistics and confidence
intervals on benchmark experiment results. It includes both parametric
(Student's t-distribution) and non-parametric (Le Boudec) methods for
computing confidence intervals.
"""

import math
from typing import List, Tuple
from collections import namedtuple

import numpy as np
import scipy.stats as st

# Named tuple for basic statistics results
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

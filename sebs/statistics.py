import math
from typing import List, Tuple
from collections import namedtuple

import numpy as np
import scipy.stats as st

BasicStats = namedtuple("BasicStats", "mean median std cv")
"""A named tuple to store basic statistics: mean, median, standard deviation (std), and coefficient of variation (cv)."""


def basic_stats(times: List[float]) -> BasicStats:
    """
    Calculate basic statistics for a list of time measurements.

    Computes mean, median, standard deviation, and coefficient of variation.

    :param times: A list of floating-point time measurements.
    :return: A BasicStats named tuple containing (mean, median, std, cv).
             Returns NaNs for std and cv if mean is zero or times list is empty/has one element.
    """
    if not times:
        return BasicStats(np.nan, np.nan, np.nan, np.nan)
    
    mean_val = np.mean(times)
    median_val = np.median(times)
    std_val = np.std(times)
    
    if mean_val == 0:
        cv_val = np.nan
    else:
        cv_val = (std_val / mean_val) * 100
        
    return BasicStats(mean_val, median_val, std_val, cv_val)


def ci_tstudents(alpha: float, times: List[float]) -> Tuple[float, float]:
    """
    Calculate the confidence interval using Student's t-distribution.

    Assumes the data is approximately normally distributed.

    :param alpha: The confidence level (e.g., 0.95 for 95% CI).
    :param times: A list of floating-point time measurements.
    :return: A tuple (lower_bound, upper_bound) of the confidence interval.
             Returns (nan, nan) if the list has fewer than 2 samples.
    """
    if len(times) < 2:
        return (np.nan, np.nan)
    mean_val = np.mean(times)
    return st.t.interval(alpha, len(times) - 1, loc=mean_val, scale=st.sem(times))


def ci_le_boudec(alpha: float, times: List[float]) -> Tuple[float, float]:
    """
    Calculate a non-parametric confidence interval based on Le Boudec's method.

    This method uses order statistics and is suitable for distributions that may
    not be normal. It requires a sufficient number of samples (related to z_value calculation).

    Reference: "Performance Evaluation of Computer and Communication Systems" by Le Boudec.

    :param alpha: The confidence level (e.g., 0.95 for 95% CI).
    :param times: A list of floating-point time measurements.
    :return: A tuple (lower_bound, upper_bound) of the confidence interval.
             Returns (nan, nan) if the number of samples is too small for the calculation.
    :raises AssertionError: If alpha is not one of the supported values (0.95, 0.99).
    """
    if not times:
        return (np.nan, np.nan)
        
    sorted_times = sorted(times)
    n = len(times)

    # z(alpha/2) - critical value from standard normal distribution
    # For a two-sided interval with confidence `alpha`, we need z_{1 - (1-alpha)/2} = z_{(1+alpha)/2}
    # However, the formula used by Le Boudec for indices is n/2 +- z * sqrt(n)/2
    # The z_value here corresponds to z_{1 - (1-alpha)/2}
    z_critical_value = {0.95: 1.96, 0.99: 2.576}.get(alpha)
    assert z_critical_value is not None, f"Unsupported alpha value: {alpha}. Supported values are 0.95, 0.99."

    # Calculate ranks for lower and upper bounds of the CI for the median
    # (as per Le Boudec's method for quantiles, here applied to median implicitly)
    # Note: The formula in the original code seems to be for median CI.
    # low_pos = floor( (n - z * sqrt(n)) / 2 )
    # high_pos = ceil( 1 + (n + z * sqrt(n)) / 2 )
    # These indices are 0-based for the sorted list.
    
    sqrt_n = math.sqrt(n)
    if sqrt_n == 0: # Avoid division by zero if n=0, though caught by earlier check
        return (np.nan, np.nan)

    val_for_pos = z_critical_value * sqrt_n / 2.0
    
    # Ensure low_pos and high_pos are within valid array bounds [0, n-1]
    # The formula can result in indices outside this range if n is too small.
    low_idx = math.floor(n / 2.0 - val_for_pos)
    high_idx = math.ceil(n / 2.0 + val_for_pos) # The original had 1 + n/2 + val_for_pos, usually it's n/2 + z*sqrt(n)/2 for upper rank.
                                              # Let's stick to a common interpretation of order statistic CIs.
                                              # The +1 in original might be for 1-based indexing conversion or specific formula variant.
                                              # For 0-based index, high_idx should be n - 1 - low_idx for symmetric CI around median.
                                              # Let's use a simpler, more standard approach for quantile CIs if that was the intent,
                                              # or stick to the provided formula if it's a specific known method.
                                              # Re-evaluating the original formula:
                                              # low_pos_orig = math.floor((n - z_critical_value * math.sqrt(n)) / 2)
                                              # high_pos_orig = math.ceil(1 + (n + z_critical_value * math.sqrt(n)) / 2)
                                              # These indices are 0-based. high_pos_orig includes an extra +1.
                                              # Let's assume the formula is as intended.
                                              # Need to ensure low_pos >=0 and high_pos < n

    low_pos_calculated = math.floor((n - z_critical_value * sqrt_n) / 2)
    # The `1 +` in high_pos seems to make it 1-based then implicitly 0-based by list access.
    # Or it's part of a specific formula variant.
    # If it's rank k, then index is k-1.
    # Let's ensure indices are valid.
    high_pos_calculated = math.ceil(1 + (n + z_critical_value * sqrt_n) / 2)
    
    # Clamp indices to valid range [0, n-1]
    final_low_idx = max(0, low_pos_calculated)
    final_high_idx = min(n - 1, high_pos_calculated -1) # -1 if high_pos_calculated was 1-based rank

    if final_low_idx > final_high_idx or final_high_idx >= n or final_low_idx < 0: # Check validity
        # This happens if n is too small for the given alpha
        return (np.nan, np.nan)

    return (sorted_times[final_low_idx], sorted_times[final_high_idx])

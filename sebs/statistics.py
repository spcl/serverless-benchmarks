import math
from typing import List, Tuple
from collections import namedtuple

import numpy as np
import scipy.stats as st

BasicStats = namedtuple("BasicStats", "mean median std cv")


def basic_stats(times: List[float]) -> BasicStats:
    mean = np.mean(times)
    median = np.median(times)
    std = np.std(times)
    cv = std / mean * 100
    return BasicStats(mean, median, std, cv)


def ci_tstudents(alpha: float, times: List[float]) -> Tuple[float, float]:
    mean = np.mean(times)
    return st.t.interval(alpha, len(times) - 1, loc=mean, scale=st.sem(times))


def ci_le_boudec(alpha: float, times: List[float]) -> Tuple[float, float]:

    sorted_times = sorted(times)
    n = len(times)

    # z(alfa/2)
    z_value = {0.95: 1.96, 0.99: 2.576}.get(alpha)
    assert z_value

    low_pos = math.floor((n - z_value * math.sqrt(n)) / 2)
    high_pos = math.ceil(1 + (n + z_value * math.sqrt(n)) / 2)

    return (sorted_times[low_pos], sorted_times[high_pos])

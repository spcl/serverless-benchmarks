import copy
import math
import logging
from typing import Dict, List, Tuple
from collections import namedtuple

import numpy as np
import scipy.stats as st

from sebs.experiments.result import Result as ExperimentResult

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


def print_stats(logger: logging.Logger, experiments: ExperimentResult):

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

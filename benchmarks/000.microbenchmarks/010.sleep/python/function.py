# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

from time import sleep, perf_counter_ns

def handler(event):

    # start timing
    sleep_time = event.get('sleep')
    start = perf_counter_ns()
    sleep(sleep_time)
    elapsed_ns = perf_counter_ns() - start
    return { 'result': elapsed_ns / 1e9 }

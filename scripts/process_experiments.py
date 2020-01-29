#!/usr/bin/env python3

import argparse
import json
import os

import pandas as pd
import numpy as np

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark_dir', type=str, help='Benchmark dir')
parser.add_argument('output_dir', type=str, help='Output dir')
args = parser.parse_args()

class TimeExperiment:

    def __init__(self, cfg, output_dir):
        print(cfg)
        pass

class MemExperiment:
    def __init__(self, cfg, output_dir):
        pass

class DiskIOExperiment:
    def __init__(self, cfg, output_dir):
        pass

class PAPIExperiment:
    def __init__(self, cfg, output_dir):
        pass

experiment_types = {
    'time': TimeExperiment,
    'papi': PAPIExperiment,
    'memory': MemExperiment,
    'disk-io': DiskIOExperiment
}

summary_file = os.path.join(args.benchmark_dir, 'experiments.json')
experiments_summary = json.load( open(summary_file, 'r') )

for name, data in experiments_summary['experiments'].items():
    benchmark_type = data['config']['benchmark']['type']
    print(benchmark_type)
    processer = experiment_types[benchmark_type](data, args.output_dir)

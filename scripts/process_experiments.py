#!/usr/bin/env python3

import argparse
import json
import math
import os

import pandas as pd
import numpy as np

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark_dir', type=str, help='Benchmark dir')
parser.add_argument('output_dir', type=str, help='Output dir')
args = parser.parse_args()

class TimeExperiment:

    def __init__(self, name, cfg, benchmark_dir, output_dir):
        self._name = name
        self._cfg = cfg
        self._out_dir = output_dir
        self._benchmark_dir = benchmark_dir

    def process(self):

        for idx, instance in enumerate(self._cfg['instances']):
            assert len(instance['results']) == 1
            result = instance['results'][0]
            result_full_path = os.path.join(self._benchmark_dir, result)
            df = pd.read_csv(open(result_full_path, 'r'), comment='#')
            if self._name == 'time_warm':
                ret = self.process_warm_times(df)
            else:
                ret = self.process_cold_times(df)
            ret.to_csv(os.path.join(self._out_dir, self._name + '.csv'), sep=',')

    @staticmethod
    def compute_stats(df):
        number_of_samples = df.shape[0]
        res = pd.DataFrame(columns=['mean', 'median', 'std', 'min', 'max', 'coef_var'])
        res['mean'] = df.mean(axis=0)
        res['median'] = df.median(axis=0)
        res['percentile_25'] = df.quantile(.25)
        res['percentile_75'] = df.quantile(.75)
        res['std'] = df.std(axis=0)
        res['min'] = df.min(axis=0)
        res['max'] = df.max(axis=0)
        res['coef_var'] = res['std'] / res['mean']

        # known standard deviation
        # mean +- dev * z  * std_dev / sqrt(n)
        ci_levels = [ (95, 1.96), (99, 2.576) ]
        for level in ci_levels:
            low = res['mean'] - level[1] * res['std'] / math.sqrt(number_of_samples)
            high = res['mean'] + level[1] * res['std'] / math.sqrt(number_of_samples)
            res['ci_{l}_low'.format(l=level[0])] = low
            res['ci_{l}_high'.format(l=level[0])] = high
        return res

    '''
        Time unit: ms
    '''
    def process_warm_times(self, df):
        # skip first warm-up row
        df.drop(df.index[0], inplace=True)
        df /= 1000.0
        df['CPU Utilization'] = (df['User'] + df['Sys']) / df['Duration']
        subset = df[['Duration', 'User', 'Sys', 'CPU Utilization']]
        return TimeExperiment.compute_stats(subset)

    def process_cold_times(self, df):
        df *= 1000.0
        df['CPU Utilization'] = (df['User'] + df['Sys']) / df['Wallclock']
        subset = df[['Wallclock', 'User', 'Sys', 'CPU Utilization']]
        return TimeExperiment.compute_stats(subset)

class MemExperiment:
    def __init__(self, name, benchmark_dir, cfg, output_dir):
        pass
    def process(self):
        pass

class DiskIOExperiment:
    def __init__(self, name, benchmark_dir, cfg, output_dir):
        pass
    def process(self):
        pass

class PAPIExperiment:
    def __init__(self, name, benchmark_dir, cfg, output_dir):
        pass
    def process(self):
        pass

experiment_types = {
    'time': TimeExperiment,
    'papi': PAPIExperiment,
    'memory': MemExperiment,
    'disk-io': DiskIOExperiment
}

summary_file = os.path.join(args.benchmark_dir, 'experiments.json')
experiments_summary = json.load( open(summary_file, 'r') )
os.makedirs(args.output_dir, exist_ok=True)

for name, data in experiments_summary['experiments'].items():
    benchmark_type = data['config']['benchmark']['type']
    print(benchmark_type)
    processer = experiment_types[benchmark_type](name, data, args.benchmark_dir, args.output_dir)
    processer.process()

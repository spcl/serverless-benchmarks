#!/usr/bin/env python3

import argparse
import json
import logging
import math
import os

import pandas as pd
import numpy as np

parser = argparse.ArgumentParser(description='Run local app experiments.')
parser.add_argument('benchmark_dir', type=str, help='Benchmark dir')
parser.add_argument('output_dir', type=str, help='Output dir')
args = parser.parse_args()

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

class Experiment:
    def __init__(self, name, cfg, benchmark_dir, output_dir):
        self._name = name
        self._cfg = cfg
        self._out_dir = output_dir
        self._benchmark_dir = benchmark_dir

class TimeExperiment(Experiment):

    def __init__(self, name, cfg, benchmark_dir, output_dir):
        super().__init__(name, cfg, benchmark_dir, output_dir)

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

    '''
        Time unit: ms
    '''
    def process_warm_times(self, df):
        # skip first warm-up row
        df.drop(df.index[0], inplace=True)
        df /= 1000.0
        df['CPU Utilization'] = (df['User'] + df['Sys']) / df['Duration']
        subset = df[['Duration', 'User', 'Sys', 'CPU Utilization']]
        return compute_stats(subset)

    def process_cold_times(self, df):
        df *= 1000.0
        df['CPU Utilization'] = (df['User'] + df['Sys']) / df['Wallclock']
        subset = df[['Wallclock', 'User', 'Sys', 'CPU Utilization']]
        return compute_stats(subset)

class MemExperiment(Experiment):

    def __init__(self, name, cfg, benchmark_dir, output_dir):
        super().__init__(name, cfg, benchmark_dir, output_dir)
        self._reps = cfg['config']['benchmark']['repetitions']

    def process(self):
        for idx, instance in enumerate(self._cfg['instances']):
            assert len(instance['results']) == 1
            result = instance['results'][0]
            result_full_path = os.path.join(self._benchmark_dir, result)
            df = pd.read_csv(open(result_full_path, 'r'), comment='#')
            if self._name == 'mem-single':
                self.process_mem_single(df)
            else:
                pass

    def process_mem_single(self, df):
        df /= 1024
        memory_max = df.max()
        logging.info(
            'Memory. Max USS %.2f PSS %.2f RSS %.2f Repetitions: %d',
            memory_max['USS'],
            memory_max['PSS'],
            memory_max['RSS'],
            self._reps
        )

class DiskIOExperiment:
    def __init__(self, name, cfg, benchmark_dir, output_dir):
        pass
    def process(self):
        pass

class PAPIExperiment(Experiment):


    def __init__(self, name, cfg, benchmark_dir, output_dir):
        super().__init__(name, cfg, benchmark_dir, output_dir)

    def process(self):
        implementations = {
            'cycles_papi': PAPIExperiment.process_cycles,
            'cache_papi': PAPIExperiment.process_caches,
            'dp_flops_papi': PAPIExperiment.process_dp_flops,
            'sp_flops_papi': PAPIExperiment.process_sp_flops,
            'inscount_papi': PAPIExperiment.process_inscount
        }

        name = self._cfg['config']['benchmark']['name']
        for idx, instance in enumerate(self._cfg['instances']):
            assert len(instance['results']) == 1
            assert len(instance['config']) == 1
            result = instance['results'][0]
            json_cfg = instance['config'][0]
            result_full_path = os.path.join(self._benchmark_dir, result)
            config_full_path = os.path.join(self._benchmark_dir, json_cfg)
            df = pd.read_csv(open(result_full_path, 'r'), comment='#')
            config = json.load(open(config_full_path, 'r'))
            ret = implementations[name](df, config)
            if ret is not None:
                ret.to_csv(os.path.join(self._out_dir, self._name + '.csv'), sep=',')

    @staticmethod
    def process_rows(df, timestamps, processer):
        current_timestamp_idx = 0
        current_timestamp_end = float(timestamps[0][1])
        prev_row = None
        results = []
        for index, row in df.iterrows():
            time = row['Time']
            # we reached new repetition
            if time > current_timestamp_end:
                current_timestamp_idx += 1
                current_timestamp_end = float(timestamps[current_timestamp_idx][1])

                results.append(processer(prev_row))
            prev_row = row
        # last datapoint
        results.append(processer(prev_row))
        # drop first result
        results = results[1:]
        return results

    @staticmethod
    def process_cycles(df, config):

        def process(row):
            cycles = int(row['PAPI_TOT_CYC'])
            return [
                cycles,
                float(row['PAPI_TOT_INS'])/cycles,
                int(row['PAPI_STL_ICY'])/cycles,
                int(row['PAPI_STL_CCY'])/cycles,
                int(row['PAPI_RES_STL'])/cycles
            ]

        timestamps = config['experiment']['timestamps']
        results = PAPIExperiment.process_rows(df, timestamps, process)
        new_df = pd.DataFrame(
            data=results,
            columns=[
                'cycles', 'ipc', 'stalled_cycles_issue',
                'stalled_cycles_retire', 'stalled_cycles_resource'
            ]
        )
        return compute_stats(new_df)

    @staticmethod
    def process_caches(df, config):

        def process(row):
            ins = int(row['PAPI_TOT_INS'])
            return [
                ins,
                float(row['PAPI_L1_ICM'])/ins*1e4,
                float(row['PAPI_L1_DCM'])/ins*1e4,
                float(row['PAPI_L2_TCM'])/ins*1e4,
                float(row['PAPI_L3_TCM'])/ins*1e4
            ]

        timestamps = config['experiment']['timestamps']
        results = PAPIExperiment.process_rows(df, timestamps, process)
        new_df = pd.DataFrame(
            data=results,
            columns=[
                'ins', 'l1_imiss_1k', 'l1_dmiss_1k',
                'l2_miss_1k', 'l3_miss_1k'
            ]
        )
        return compute_stats(new_df)

    @staticmethod
    def process_dp_flops(df, config):
        pass

    @staticmethod
    def process_sp_flops(df, config):
        pass

    @staticmethod
    def process_inscount(df, config):
        def process(row):
            ins = int(row['PAPI_TOT_INS'])
            return [
                ins,
                float(row['PAPI_LST_INS'])/ins,
                float(row['PAPI_BR_INS'])/ins,
                float(row['PAPI_BR_MSP'])/ins*1e4
            ]
        timestamps = config['experiment']['timestamps']
        results = PAPIExperiment.process_rows(df, timestamps, process)
        new_df = pd.DataFrame(
                data=results,
                columns=['instructions', 'load_stores', 'branches', 'br_mispr_1k']
        )
        return compute_stats(new_df)

experiment_types = {
    'time': TimeExperiment,
    'papi': PAPIExperiment,
    'memory': MemExperiment,
    'disk-io': DiskIOExperiment
}

os.makedirs(args.output_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(args.output_dir, 'out.log'),
    filemode='w',
    format='%(message)s',
    level=logging.INFO
)

summary_file = os.path.join(args.benchmark_dir, 'experiments.json')
experiments_summary = json.load( open(summary_file, 'r') )

for name, data in experiments_summary['experiments'].items():
    benchmark_type = data['config']['benchmark']['type']
    processer = experiment_types[benchmark_type](name, data, args.benchmark_dir, args.output_dir)
    processer.process()

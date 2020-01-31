
import datetime
import json
import logging
import os
import requests
import time

import multiprocessing
from multiprocessing import pool
from multiprocessing.pool import ThreadPool
from typing import List

import boto3

from cache import cache
from CodePackage import CodePackage

def invoke(idx, url, json_data):
    begin = datetime.datetime.now()
    headers = {'content-type': 'application/json'}
    with requests.post(url, headers=headers, json=json_data) as req:
        end = datetime.datetime.now()
        if req.status_code != 200:
            data = {
                'idx': idx,
                'begin': begin,
                'code': req.status_code,
                'reason': req.reason
            }
            raise RuntimeError(
                ('Request {idx} at {begin} finished with status'
                 'code {code}! Reason: {reason}').format(**data)
            )
        body = json.loads(req.json()['body'])
        data = {
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'cold': body['is_cold'],
            'duration': 0,
            'response': body
        }
        logging.info('Processed request! Start {begin} End {end} Cold? {cold} Duration {duration}'.format(**data))
        return data


class CloudExperiment:
    pass

class TimeWarmExperiment:
    pass

class ColdStartExperiment:

    def __init__(self, sleep_time, fname, invocations,
            process_id, thread_id, out_dir, memory, timeout):
        self._sleep_time = sleep_time
        self._invocations = invocations
        self._out_dir = out_dir
        self._pid = process_id
        self._tid = thread_id
        self._fname = fname
        self._memory = memory
        self._timeout = timeout

    def test(self, repetition, invocations, url, json_data):

        logging.info('P {} T {} Sleep {} F {} Url {}'.format(
            self._pid, self._tid, self._sleep_time, self._fname, url
        ))
        first_begin = datetime.datetime.now()
        first_data = invoke(repetition, url, json_data)
        if not first_data['cold']:
            raise RuntimeError('First invocation not cold on {rep}'.format(rep=repetition))

        # sleep
        time_spent = float(datetime.datetime.now().strftime('%s.%f')) - float(first_data['end'])
        seconds_sleep = self._sleep_time - time_spent
        time.sleep(seconds_sleep)

        # run again!
        second_begin = datetime.datetime.now()
        second_data = invoke(repetition, url, json_data)
        return {
            'idx': repetition,
            'sleep_time': self._sleep_time,
            'first_begin': first_begin.strftime('%s.%f'),
            'second_begin': second_begin.strftime('%s.%f'),
            'first_result': first_data,
            'second_result': second_data
        }

def run(repetitions, urls, fnames, sleep_times, input_data,
        invocations, process_id, out_dir, memory, timeout):
  
    threads=len(urls)
    # wait before starting 
    b = multiprocessing.Semaphore(invocations)
    b.acquire()

    final_results = []
    with ThreadPool(threads) as pool:
        results = []
        for idx, url in enumerate(urls):
            exp = ColdStartExperiment(sleep_times[idx], fnames[idx],
                    invocations, process_id, idx, out_dir, memory, timeout)
            results.append(
                pool.apply_async(exp.test, args=(repetitions, invocations, url, input_data))
            )
            time.sleep(0.091)
        final_results = [result.get() for result in results]
    return final_results

class ExperimentRunner:

    def __init__(self, benchmark: str,
            output_dir: str,
            language: str,
            input_config: dict,
            experiment_config: dict,
            code_package: CodePackage,
            deployment_client, cache_client: cache):
        cached_f, path = cache_client.get_function(
                deployment=deployment_client.name,
                benchmark=benchmark,
                language=language
        )
        #url = cached_f['url']
        #invoke(0, url, input_config)
        function_names = []
        fname = cached_f['name']
        memory = 128
        timeout = 120
        invocations = 4
        repetitions = 5
        #times = [1, 2, 5]
        sleep_time=1
        input_config['sleep'] = sleep_time
        times = [1, 2,5]
        for t in times:
            function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, sleep_time, invocations, t))
        deployment_client.delete_function(function_names)
        #urls = function_names
        urls = deployment_client.create_function_copies(function_names, code_package, experiment_config)
        #print(urls)
        idx = 0
        json_results = [[]] * len(times)
        json_results = {}
        for t in times:
            json_results[t] = []
        
        with multiprocessing.Pool(processes=invocations) as pool:
            while idx < repetitions:
                for i, t in enumerate(times):
                    json_results[t].append([])
                results = []
                for i in range(0, invocations):
                    results.append(
                        pool.apply_async(run, args=(idx,
                            urls, function_names, times, input_config, invocations,
                            i, output_dir, 128, 120))
                    )
                for result in results:
                    ret = result.get()
                    for i, val in enumerate(ret):
                        json_results[times[i]][-1].append(val)
                idx += 1
                for fname in function_names:
                    deployment_client.client.update_function_configuration(
                        FunctionName=fname,
                        Timeout=timeout + idx,
                        MemorySize=memory
                    )
        fname = 'results_{invocations}_{repetition}_{memory}_{sleep}.json'.format(
                invocations=invocations,
                repetition=repetitions,
                memory=memory,
                sleep=sleep_time
        )
        results = {
            'invocations': invocations,
            'repetition': repetitions,
            'wait_times': times,
            'results': json_results
        }
        json.dump(results, open(os.path.join(output_dir, fname), 'w'), indent=2)
        deployment_client.delete_function(function_names)
        #threads=10
        #futures = []
        #with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        #    for idx in range(0, threads):
        #        futures.append(executor.submit(invoke, idx, url, input_config))
        #self._pool = Pool(5)
        #print(cached_f)





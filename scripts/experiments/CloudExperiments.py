
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

def invoke(tid, idx, url, json_data):
    begin = datetime.datetime.now()
    headers = {'content-type': 'application/json'}
    with requests.post(url, headers=headers, json=json_data) as req:
        end = datetime.datetime.now()
        if req.status_code != 200:
            data = {
                'idx': idx,
                'begin': begin,
                'url': url,
                'code': req.status_code,
                'reason': req.reason
            }
            raise RuntimeError(
                ('Request {idx} at {begin} for {url} finished with status'
                 'code {code}! Reason: {reason}').format(**data)
            )
        if 'body' in req.json():
            if isinstance(req.json()['body'], str):
                body = json.loads(req.json()['body'])
            else:
                body = req.json()['body']
        else:
            body = req.json()
        data = {
            'begin': begin.strftime('%s.%f'),
            'end': end.strftime('%s.%f'),
            'cold': body['is_cold'],
            'tid': tid,
            'duration': 0,
            'response': body
        }
        logging.info('Processed request! Tid: {tid} Start {begin} End {end} Cold? {cold} Duration {duration}'.format(**data))
        return data


class CloudExperiment:
    pass

class TimeWarmExperiment:
    pass

class ColdStartExperiment:

    def __init__(self, sleep_time, fname, invocations,
            process_id, thread_id, out_dir):
        self._sleep_time = sleep_time
        self._invocations = invocations
        self._out_dir = out_dir
        self._pid = process_id
        self._tid = thread_id
        self._fname = fname

    def test(self, tid, repetition, invocations, url, json_data):

        logging.info('P {} T {} Sleep {} F {} Url {}'.format(
            self._pid, self._tid, self._sleep_time, self._fname, url
        ))
        try:
            first_begin = datetime.datetime.now()
            first_data = invoke(tid, repetition, url, json_data)
            if not first_data['cold']:
                logging.error('First invocation not cold on time {t} rep {rep} pid {pid} tid {tid}'.format(t=self._sleep_time,rep=repetition,pid=self._pid,tid=self._tid))
                #return {
                #    'idx': repetition,
                #    'sleep_time': self._sleep_time,
                #    'first_begin': first_begin.strftime('%s.%f'),
                #    'second_begin': 0,
                #    'first_result': first_data,
                #    'second_result': {}
                #}
        except:
            logging.error('FIRST Failed at function {}', self._fname)
            raise RuntimeError()

        # sleep
        time_spent = float(datetime.datetime.now().strftime('%s.%f')) - float(first_data['end'])
        seconds_sleep = self._sleep_time - time_spent
        time.sleep(seconds_sleep)

        # run again!
        try:
            second_begin = datetime.datetime.now()
            second_data = invoke(tid, repetition, url, json_data)
        except:
            logging.error('Second Failed at function {}', self._fname)
        return {
            'idx': repetition,
            'sleep_time': self._sleep_time,
            'first_begin': first_begin.strftime('%s.%f'),
            'second_begin': second_begin.strftime('%s.%f'),
            'first_result': first_data,
            'second_result': second_data
        }

def run(repetitions, urls, fnames, sleep_times, input_data,
        invocations, process_id, out_dir):
  
    threads=len(urls)
    # wait before starting 
    b = multiprocessing.Semaphore(invocations)
    b.acquire()

    sleep_time = process_id % 4
    logging.info('Process {} will sleep {} for each invocation'.format(process_id, sleep_time))

    final_results = []
    with ThreadPool(threads) as pool:
        results = [None] * len(urls)
        #for idx, url in reversed(list(enumerate(urls))):
        #for idx, url in enumerate(urls):
        for idx in reversed(range(0, len(urls))):
            time.sleep(sleep_time)
            url = urls[idx]
            exp = ColdStartExperiment(sleep_times[idx], fnames[idx],
                    invocations, process_id, idx, out_dir)
            logging.info('Process {pid} begins url {url} with sleep {sleep} func {func}'.format(pid=process_id, url=url,sleep=sleep_times[idx],func=fnames[idx]))
            results[idx] =  pool.apply_async(exp.test, args=(idx, repetitions, invocations, url, input_data))
            time.sleep(10.091)
            #time.sleep(0.091)
        failed = False
        for result in results:
            try:
                final_results.append(result.get())
            except Exception as e:
                logging.error(e)
                failed = True
        if failed:
            raise RuntimeError()
        #final_results = [result.get() for result in results]
    return final_results

class ExperimentRunner:

    def __init__(self,
            update_before_launch: bool,
            config_file: str,
            invocations: int,
            repetitions: int,
            sleep_time: int,
            memory: int,
            times_begin_idx: int,
            times_end_idx: int,
            benchmark: str,
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
        timeout = 850
        #times = [1, 2, 5]
        input_config['sleep'] = sleep_time

        times = [1, 2, 4, 8, 15, 30, 60, 120, 180, 240, 300, 360, 480, 600, 720, 900, 1080, 1200, 420, 540,660,780,840,960,1020,1140,1260,1320]
        #times = [360, 480, 600, 720, 900, 1080, 1200]
        if False:
            invoc_begin=1
            invoc_end=21
            name = 'experiment_1'
            times = times[times_begin_idx:times_end_idx+1]
            logging.info('Work on times {}'.format(times))
            urls_config = json.load(open('/users/mcopik/projects/serverless-benchmarks/serverless-benchmarks/{}_20.experiment'.format(name), 'r'))
            for invoc in range(invoc_begin, invoc_end):
                for t in times:
                    function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, sleep_time, invoc, t))
            deployment_client.delete_function(function_names)
            #urls = function_names
            URLS = {}
            for invoc in range(invoc_begin, invoc_end):
                function_names = []
                for t in times:
                    function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, sleep_time, invoc, t))
                logging.info(function_names)

                api_id = urls_config[str(invoc)]['restApiId']
                api_name = urls_config[str(invoc)]['restApi']
                #api_name = '{}_{}_{}'.format(fname, memory, invoc)

                urls, api_id = deployment_client.create_function_copies(function_names, api_name, memory, timeout, code_package, experiment_config, api_id)
                #URLS[invoc] = {'names': function_names, 'urls': urls, 'restApi': '{}_{}_{}'.format(fname, memory, invocations), 'restApiId': api_id }

                urls_config[str(invoc)]['names'].extend(function_names)
                urls_config[str(invoc)]['urls'].extend(urls)

                json.dump(urls_config, open('{}_{}.experiment'.format(name, invoc), 'w'), indent=2)
            return
        else:
            name = 'experiment_1'
            urls_config = json.load(open(config_file))
            urls = urls_config[str(invocations)]['urls']
            urls = urls[times_begin_idx:times_end_idx+1]
            times = times[times_begin_idx:times_end_idx+1]
            logging.info('Work on times {}'.format(times))
            logging.info('Work on urls {}'.format(urls))
           
            function_names = urls_config[str(invocations)]['names']
            function_names = function_names[times_begin_idx:times_end_idx+1]
            #for t in times:
                #function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, 1, invocations, t))
                #function_names.append('{}_{}_{}_{}_{}'.format(fname, 128, 1, invocations, t))
        idx = 0
        json_results = [[]] * len(times)
        json_results = {}
        for t in times:
            json_results[t] = []
        logging.info('Running functions {}'.format(function_names))
        logging.info('Using urls {}'.format(urls)) 

        # Make sure it's cold and update memory
        if update_before_launch:
            deployment_client.start_lambda()
            for idx, fname in enumerate(function_names):
                while True:
                    try: 
                        deployment_client.client.update_function_configuration(
                            FunctionName=fname,
                            Timeout=timeout,
                            MemorySize=memory+128
                        )
                        logging.info('Updated {} to timeout {}'.format(function_names[idx], timeout))
                        break
                    except Exception as e:
                        logging.info('Repeat update...')
                        logging.info(e)
                        continue
            time.sleep(30)
            for idx, fname in enumerate(function_names):
                while True:
                    try: 
                        deployment_client.client.update_function_configuration(
                            FunctionName=fname,
                            Timeout=timeout,
                            MemorySize=memory
                        )
                        logging.info('Updated {} to timeout {}'.format(function_names[idx], timeout))
                        break
                    except Exception as e:
                        logging.info('Repeat update...')
                        logging.info(e)
                        continue
        logging.info('Start {} invocations with {} times'.format(invocations, len(times)))
        idx = 0
        fname = 'results_{invocations}_{repetition}_{memory}_{sleep}.json'.format(
                invocations=invocations,
                repetition=repetitions,
                memory=memory,
                sleep=sleep_time
        )
        with multiprocessing.Pool(processes=invocations) as pool:
            time.sleep(15)
            while idx < repetitions:
                for i, t in enumerate(times):
                    json_results[t].append([])
                results = []
                for i in range(0, invocations):
                    results.append(
                        pool.apply_async(run, args=(idx,
                            urls, function_names, times, input_config, invocations,
                            i, output_dir))
                    )
                for result in results:
                    ret = result.get()
                    for i, val in enumerate(ret):
                        json_results[times[i]][-1].append(val)
                logging.info('Finished iteration {}'.format(idx))
                idx += 1
                if update_before_launch:
                    for fname in function_names:
                        deployment_client.client.update_function_configuration(
                            FunctionName=fname,
                            Timeout=timeout + idx,
                            MemorySize=memory+128
                        )
                    time.sleep(30)
                    for fname in function_names:
                        deployment_client.client.update_function_configuration(
                            FunctionName=fname,
                            Timeout=timeout,
                            MemorySize=memory
                        )
                        logging.info('Updated {} to timeout {}'.format(fname, timeout+idx))
                logging.info('Dumped data')
                results = {
                    'invocations': invocations,
                    'repetition': repetitions,
                    'wait_times': times,
                    'sleep_time': sleep_time,
                    'memory': memory,
                    'results': json_results
                }
                json.dump(results, open(os.path.join(output_dir, fname), 'w'), indent=2)
        logging.info('Done!')
        #deployment_client.delete_function(function_names)
        #threads=10
        #futures = []
        #with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        #    for idx in range(0, threads):
        #        futures.append(executor.submit(invoke, idx, url, input_config))
        #self._pool = Pool(5)
        #print(cached_f)

def invoke_f(url, json_data):
    begin = datetime.datetime.now()
    headers = {'content-type': 'application/json'}
    with requests.post(url, headers=headers, json=json_data) as req:
        end = datetime.datetime.now()
        if req.status_code != 200:
            data = {
                'idx': idx,
                'begin': begin,
                'url': url,
                'code': req.status_code,
                'reason': req.reason
            }
            raise RuntimeError(
                ('Request {idx} at {begin} for {url} finished with status'
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

def run(pid, invocations, url, input_data):

    # wait before starting 
    b = multiprocessing.Semaphore(invocations)
    b.acquire()

    attempts = []
    logging.info('P {} Url {}'.format(pid, url))
    begin = datetime.datetime.now()
    first_data = invoke_f(url, input_data)
    end = datetime.datetime.now()
    attempts.append({
        'begin': begin.strftime('%s.%f'),
        'end': end.strftime('%s.%f'),
        'result': first_data,
        'correct': True
        })
    if not first_data['cold']:
        logging.error('First invocation not cold on pid {pid}'.format(pid=pid))
        attempts[0]['correct'] = False
        return attempts
    logging.info('Processed first request {pid}'.format(pid=pid))
    time.sleep(5)
    b = multiprocessing.Semaphore(invocations)
    b.acquire()

    # run again!
    begin = datetime.datetime.now()
    second_data = invoke_f(url, input_data)
    end = datetime.datetime.now()
    logging.info('Processed second request {pid}'.format(pid=pid))
    attempts.append({
        'begin': begin.strftime('%s.%f'),
        'end': end.strftime('%s.%f'),
        'result': second_data,
        'correct': True
    })
    return attempts


def run_burst_experiment(
        config_file: str,
        invocations: int,
        memories: List[int],
        repetitions: int,
        benchmark: str,
        output_dir: str,
        language: str,
        input_config: dict,
        experiment_config: dict,
        deployment_client, cache_client: cache,
        additional_cfg):
    cached_f, path = cache_client.get_function(
            deployment=deployment_client.name,
            benchmark=benchmark,
            language=language
    )
    if 'invoke_url' in cached_f:
        cached_url = cached_f['invoke_url']
    elif 'url' in cached_f:
        cached_url = cached_f['url']
    else:
        raise RuntimeError()
    fname = cached_f['name']
    logging.info('Function {} URL {}'.format(fname, cached_url))

    # Make sure it's cold and update memory to new rquired
    timeout = 840

    for memory in memories:

        deployment_client.start_lambda()
        while True:
            try:
                mem_change = memory + 512 if memory < 2048 else memory - 512
                deployment_client.client.update_function_configuration(
                    FunctionName=fname,
                    Timeout=timeout,
                    MemorySize=mem_change,
                )
                logging.info('Updated {} to timeout {} mem {}'.format(fname, timeout, mem_change))
                break
            except Exception as e:
                logging.info('Repeat update...')
                logging.info(e)
                continue
        time.sleep(30)
        while True:
            try: 
                deployment_client.client.update_function_configuration(
                    FunctionName=fname,
                    Timeout=timeout,
                    MemorySize=memory
                )
                logging.info('Updated {} to timeout {} memory {}'.format(fname, timeout, memory))
                break
            except Exception as e:
                logging.info('Repeat update...')
                logging.info(e)
                continue
        time.sleep(30)
        logging.info('Start {} invocations mem {} '.format(invocations, memory))
        idx = 0
        result_file = 'results_{benchmark}_{invocations}_{repetition}_{memory}.json'.format(
                benchmark=benchmark,
                invocations=invocations,
                repetition=repetitions,
                memory=memory,
        )
        full_results = {'cold': [], 'warm': []}
        with multiprocessing.Pool(processes=invocations) as pool:
            #time.sleep(15)
            #while idx < repetitions:
                #for i, t in enumerate(times):
                #    json_results[t].append([])
            begin = datetime.datetime.now()
            results = []
            for i in range(0, invocations):
                results.append(
                    pool.apply_async(run, args=(idx, invocations, cached_url, input_config))
                )
            for result in results:
                ret = result.get()
                full_results['cold'].append(ret)
                #for i, val in enumerate(ret):
                #    json_results[times[i]][-1].append(val)
            end = datetime.datetime.now()
            logging.info('Finished iteration {}'.format(idx))
            idx += 1
                #results = []
                #for i in range(0, invocations):
                #    logging.info('Launch warm {}'.format(i))
                #    results.append(
                #        pool.apply_async(run, args=(idx, invocations, cached_url, input_config))
                #    )
                #    time.sleep(1)
                #for result in results:
                #    ret = result.get()
                #    full_results['warm'].append(ret)
                #idx += 1
                #for fname in function_names:
                #    deployment_client.client.update_function_configuration(
                #        FunctionName=fname,
                #        Timeout=timeout + idx,
                #        MemorySize=memory+128
                #    )
                #time.sleep(30)
                #for fname in function_names:
                #    deployment_client.client.update_function_configuration(
                #        FunctionName=fname,
                #        Timeout=timeout,
                #        MemorySize=memory
                #    )
                #    logging.info('Updated {} to timeout {}'.format(fname, timeout+idx))
                #logging.info('Dumped data')
            results = {
                'begin': begin.strftime('%s.%f'),
                'end': end.strftime('%s.%f'),
                'function_name': fname,
                'repetition': repetitions,
                'memory': memory,
                'results': full_results,
                'config': additional_cfg
            }
            json.dump(results, open(os.path.join(output_dir, result_file), 'w'), indent=2)
        logging.info('Done {}!'.format(memory))

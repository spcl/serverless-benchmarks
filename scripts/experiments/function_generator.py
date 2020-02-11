
import argparse
import logging
import json


'''
    We suport two basic cases:
    a) generate completely new list of functions
    b) extend existing list of functions
'''


def create_functions(deployment, cache_client, code_package, experiment_config, benchmark, language, memory, times_begin_idx, times_end_idx, sleep_time, extend=None):
    times = [1, 2, 4, 8, 15, 30, 60, 120, 180, 240, 300, 360, 480, 600, 720, 900, 1080, 1200, 420, 540,660,780,840,960,1020,1140,1260,1320]
    #times = [360, 480, 600, 720, 900, 1080, 1200]
    if deployment.name == 'aws':

        cached_f, path = cache_client.get_function(
                deployment=deployment.name,
                benchmark=benchmark,
                language=language
        )
        function_names = []
        fname = cached_f['name']
        memory = memory
        invoc_begin=1
        invoc_end=21
        timeout=870
        name = 'experiment_256'
        times = times[times_begin_idx:times_end_idx+1]
        logging.info('Work on times {}'.format(times))
        if extend:
            urls_config = json.load(open(extend, 'r'))
        else:
            urls_config = None
            api_id = None
            api_name = None
        function_names = []
        for invoc in range(invoc_begin, invoc_end):
            for t in times:
                function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, sleep_time, invoc, t))
        logging.info('Remove functions {}'.format(function_names))
        #deployment_client.delete_function(function_names)
        #urls = function_names
        URLS = {}
        for invoc in range(invoc_begin, invoc_end):
            function_names = []
            for t in times:
                function_names.append('{}_{}_{}_{}_{}'.format(fname, memory, sleep_time, invoc, t))

            if extend:
                api_id = urls_config[str(invoc)]['restApiId']
                api_name = urls_config[str(invoc)]['restApi']
            else:
                api_name = '{}_{}_{}'.format(fname, memory, invoc)
                api_id = None

            logging.info('Create function {} with memory {} and api: {}, {}'.format(function_names, memory, api_name, api_id))
            #continue
            #urls = []
            #api_id = 'api'
            urls, api_id = deployment.create_function_copies(function_names, api_name, memory, timeout, code_package, experiment_config, api_id)

            if urls_config:
                urls_config[str(invoc)]['names'].extend(function_names)
                urls_config[str(invoc)]['urls'].extend(urls)
            else:
                URLS[invoc] = {'names': function_names, 'urls': urls, 'restApi': api_name, 'restApiId': api_id }

            if urls_config:
                json.dump(urls_config, open('{}_{}_{}.experiment'.format(name, invoc, memory), 'w'), indent=2)
            else:
                json.dump(URLS, open('{}_{}_{}.experiment'.format(name, invoc, memory), 'w'), indent=2)
        return
    elif deployment.name == 'azure':
        cached_f, path = cache_client.get_function(
                deployment=deployment.name,
                benchmark=benchmark,
                language=language
        )
        function_names = []
        fname = cached_f['name']
        memory = memory
        #invoc_begin=16
        #invoc_end=21
        #invocs = [2, 3, 4, 5]
        #invocs = [6,7,8]
        #invocs = [10,11,12,13]
        invocs = [16,17,18,19]
        name = 'experiment_azure'
        times = times[times_begin_idx:times_end_idx+1]
        logging.info('Work on times {}'.format(times))
        if extend:
            urls_config = json.load(open(extend, 'r'))
        else:
            urls_config = None
        function_names = []
        #for invoc in range(invoc_begin, invoc_end):
        #    for t in times:
        #        function_names.append('{}-{}{}-{}-{}'.format(fname, memory, sleep_time, invoc, t))
        #logging.info('Remove functions {}'.format(function_names))
        URLS = {}
        logging.info('Work on {}'.format(invocs))
        for invoc in invocs: #range(invoc_begin, invoc_end):
            function_names = []
            for t in times:
                function_names.append('{}-{}-{}-{}-{}'.format(fname, memory, sleep_time, invoc, t))

            logging.info('Create functions {}'.format(function_names))
            names, urls = deployment.create_function_copies(function_names, code_package, experiment_config)
            print(names, urls)

            if urls_config:
                urls_config[str(invoc)]['names'].extend(names)
                urls_config[str(invoc)]['urls'].extend(urls)
            else:
                URLS[invoc] = {'names': names, 'urls': urls }

            print(URLS) 
            if urls_config:
                json.dump(urls_config, open('{}_{}_azure.experiment'.format(name, invoc), 'w'), indent=2)
            else:
                print('Dump data {}'.format('{}_{}_azure.experiment'.format(name, invoc)))
                json.dump(URLS, open('{}_{}_azure.experiment'.format(name, invoc), 'w'), indent=2)
        return
    else:
        pass

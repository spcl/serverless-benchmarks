
import datetime, json, sys, traceback, csv

from utils import *
from tools import *

# imported function
from function import function

import pypapi.exceptions

class papi_benchmarker:
    from pypapi import papi_low as papi
    from pypapi import events as papi_events

    def __init__(self, papi_cfg):
        self.events = []
        self.events_names = []
        self.count = 0

        self.papi.library_init()
        self.events = self.papi.create_eventset()
        for event in papi_cfg['events']:
            try:
                self.papi.add_event(self.events, getattr(self.papi_events, event))
            except pypapi.exceptions.PapiInvalidValueError as err:
                print('Adding event {event} failed!'.format(event=event))
                sys.exit(100)

        self.events_names = papi_cfg['events']
        self.count = len(papi_cfg['events'])
        self.results = []

        self.ins_granularity = papi_cfg['overflow_instruction_granularity']
        self.buffer_size = papi_cfg['overflow_buffer_size']
        self.start_time = datetime.datetime.now()
        
        self.papi.overflow_sampling(self.events, self.papi_events.PAPI_TOT_INS,
                int(self.ins_granularity), int(self.buffer_size))

    def start_overflow(self):
        self.papi.start(self.events)

    def stop_overflow(self):
        self.papi.stop(self.events)

    def get_results(self):
        data = self.papi.overflow_sampling_results(self.events)
        for vals in data:
            for i in range(0, len(vals), self.count + 1):
                chunks = vals[i:i+self.count+1]
                measurement_time = datetime.datetime.fromtimestamp(chunks[0]/1e6)
                time = (measurement_time - self.start_time) / datetime.timedelta(microseconds = 1)
                self.results.append([measurement_time.strftime("%s.%f"), time] + list(chunks[1:]))

    def finish(self):
        self.papi.cleanup_eventset(self.events)
        self.papi.destroy_eventset(self.events)


cfg = json.load(open(sys.argv[1], 'r'))
repetitions = cfg['benchmark']['repetitions']
disable_gc = cfg['benchmark']['disable_gc']
input_data = cfg['input']
papi_experiments = papi_benchmarker(cfg['benchmark']['papi'])

timedata = [0] * repetitions
try:
    start = start_benchmarking(disable_gc)
    for i in range(0, repetitions):
        begin = datetime.datetime.now()
        papi_experiments.start_overflow()
        res = function.handler(input_data)
        papi_experiments.stop_overflow()
        stop = datetime.datetime.now()
        print(res, file = open(
                get_result_prefix(LOGS_DIR, 'output', 'txt'),
                'w'
            ))
        timedata[i] = [begin, stop]
    end = stop_benchmarking()
except Exception as e:
    print('Exception caught!')
    print(e)
    traceback.print_exc()


papi_experiments.get_results()
papi_experiments.finish()
result = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'csv')
with open(result, 'w') as f:
    csv_writer = csv.writer(f)
    csv_writer.writerow(
            ['Time','RelativeTime'] + papi_experiments.events_names
        )
    for val in papi_experiments.results:
        csv_writer.writerow(val)

experiment_data = {}
experiment_data['repetitions'] = repetitions
experiment_data['timestamps'] = process_timestamps(timedata)
experiment_data['start'] = str(start)
experiment_data['end'] = str(end)
print(json.dumps({'experiment': experiment_data, 'runtime': get_config()}, indent=2))

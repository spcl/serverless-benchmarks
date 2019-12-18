import gc, sys, imp, datetime, json, os, traceback

RESULTS_DIR = 'results'
LOGS_DIR = 'logs'

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
            self.papi.add_event(self.events, getattr(self.papi_events, event))
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

def start_benchmarking():
    gc.disable()
    return datetime.datetime.now()

def stop_benchmarking():
    end = datetime.datetime.now()
    gc.enable()
    return end

def get_result_prefix(dirname, name):
    import glob
    name = os.path.join(dirname, name)
    counter = 0
    while glob.glob( '{}_{:02d}*'.format(name, counter) ):
        counter +=1
    return '{}_{:02d}'.format(name, counter)

if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1], 'r'))
    input_data = cfg['input']
    repetitions = cfg['benchmark']['repetitions']
    mod_name = cfg['benchmark']['module']
    experiments = cfg['benchmark']['experiments']

    run_timing = True if 'time' in experiments else False
    run_papi = True if 'papi' in experiments else False

    os.system('unzip -qn code.zip')
    if os.path.exists('data.zip'):
        os.system('unzip -qn data.zip -d data')

    try:
        mod = imp.load_source(mod_name, mod_name + '.py')
        handler = getattr(mod, 'handler')
    except ImportError as e:
        print('Failed to import module {} from {}'.format(mod_name, mod_name + '.py'))
        print(e)
        sys.exit(1)

    if run_timing:
        timedata = [0] * repetitions
    if run_papi:
        papi_cfg = cfg['benchmark']['papi']
        papi_experiments = papi_benchmarker(papi_cfg)
    try:
        start = start_benchmarking()
        for i in range(0, repetitions):
            begin = datetime.datetime.now()
            if run_papi:
                papi_experiments.start_overflow()
            res = handler(input_data)
            if run_papi:
                papi_experiments.stop_overflow()
            stop = datetime.datetime.now()
            print(res, file = open(
                    '{}.txt'.format(get_result_prefix(LOGS_DIR, 'output')),
                    'w'
                ))
            if run_timing:
                timedata[i] = [begin, stop]
        end = stop_benchmarking()
    except Exception as e:
        print('Exception caught!')
        print(e)
        traceback.print_exc()

    # Dump experiment data
    experiment_data = {'system' : {}, 'runtime' : {}, 'experiment': {}}
    # get currently loaded modules
    # https://stackoverflow.com/questions/4858100/how-to-list-imported-modules
    modulenames = set(sys.modules) & set(globals())
    allmodules = [sys.modules[name] for name in modulenames]
    import platform, csv
    uname = os.uname()
    for val in ['nodename', 'sysname', 'release', 'version', 'machine']:
        experiment_data['system'][val] = getattr(uname, val)

    experiment_data['runtime']['version'] = platform.python_version()
    experiment_data['runtime']['modules'] = str(allmodules)
    experiment_data['input'] = cfg

    experiment_data['experiment']['repetitions'] = repetitions
    experiment_data['experiment']['start'] = start.strftime('%s.%f')
    experiment_data['experiment']['end'] = end.strftime('%s.%f')


    # Dump results
    if run_timing:
        result = get_result_prefix(RESULTS_DIR, 'time')
        with open('{}.json'.format(result), 'w') as f:
            json.dump(experiment_data, f, indent = 2)

        with open('{}.csv'.format(result), 'w') as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow(['Begin','End','Duration'])
            for i in range(0, len(timedata)):
                csv_writer.writerow([
                        timedata[i][0].strftime('%s.%f'),
                        timedata[i][1].strftime('%s.%f'),
                        (timedata[i][1] - timedata[i][0]) /
                            datetime.timedelta(microseconds=1)
                    ])
    if run_papi:
        papi_experiments.get_results()
        papi_experiments.finish()
        result = get_result_prefix(RESULTS_DIR, 'papi')
        with open('{}.json'.format(result), 'w') as f:
            json.dump(experiment_data, f, indent = 2)
        
        with open('{}.csv'.format(result), 'w') as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow(
                    ['Time','RelativeTime'] + papi_experiments.events_names
                )
            for val in papi_experiments.results:
                csv_writer.writerow(val)


import gc, sys, imp, datetime, json, os, traceback

RESULTS_DIR = 'results'

def start_benchmarking():
    gc.disable()
    return datetime.datetime.now()

def stop_benchmarking():
    end = datetime.datetime.now()
    gc.enable()
    return end

def get_result_prefix(name):
    import glob
    name = os.path.join(RESULTS_DIR, name)
    counter = 0
    while glob.glob( '{}-{}*'.format(name, counter) ):
        counter +=1
    return '{}-{}'.format(name, counter)


if __name__ == "__main__":
    cfg = json.load(open('input.json', 'r'))
    input_data = cfg['input']
    repetitions = cfg['benchmark']['repetitions']
    mod_name = cfg['benchmark']['module']
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

    timedata = [0] * repetitions
    try:
        start = start_benchmarking()
        for i in range(0, repetitions):
            begin = datetime.datetime.now()
            handler(input_data)
            stop = datetime.datetime.now()
            timedata[i] = [begin, stop]
        end = stop_benchmarking()
    except Exception as e:
        print('Exception caught!')
        print(e)
        traceback.print_exc()

    # Dump experiment data
    experiment_data = {'system' : {}, 'date': {}, 'runtime' : {}}
    # https://stackoverflow.com/questions/4858100/how-to-list-imported-modules
    modulenames = set(sys.modules) & set(globals())
    allmodules = [sys.modules[name] for name in modulenames]
    import platform, csv
    uname = os.uname()
    for val in ['nodename', 'sysname', 'release', 'version', 'machine']:
        experiment_data['system'][val] = getattr(uname, val)
    experiment_data['date']['start'] = start.strftime('%s.%f')
    experiment_data['date']['end'] = end.strftime('%s.%f')

    experiment_data['runtime']['version'] = platform.python_version()
    experiment_data['runtime']['modules'] = str(allmodules)
    result = get_result_prefix('time')
    with open('{}.json'.format(result), 'w') as f:
        json.dump(experiment_data, f)

    # Dump results
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


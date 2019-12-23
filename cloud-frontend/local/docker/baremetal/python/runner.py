import csv, gc, sys, imp, datetime, json, os, subprocess

from utils import *

def get_language(lang):
    languages = {'python': 'python3', 'nodejs': 'nodejs'}
    return [languages[lang]]

def get_runner(experiment, options=None):
    runners = {
        'papi' : 'papi_runner.py',
        'time' : {'warm' : 'time-in-proc.py', 'cold' : 'time-out-proc.py'},
        'config': 'config.py'
    }
    return [runners[experiment][options] if options is not None else runners[experiment]]

def get_runner_cmd(lang, experiment, options):
    return get_language(lang) + get_runner(experiment, options)

if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1], 'r'))
    input_data = cfg['input']
    repetitions = cfg['benchmark']['repetitions']
    experiment = cfg['benchmark']['type']
    language = cfg['benchmark']['language']
    experiment_options = cfg['benchmark'].get('experiment_options', None)

    os.system('unzip -qn code.zip')
    if os.path.exists('data.zip'):
        os.system('unzip -qn data.zip -d data')

    # initialize data storage

    runner = get_runner_cmd(language, experiment, experiment_options)
    ret = subprocess.run(runner + [sys.argv[1]], stdout=subprocess.PIPE)

    # Dump experiment data
    result = {'system': {}, 'input': cfg} 
    uname = os.uname()
    for val in ['nodename', 'sysname', 'release', 'version', 'machine']:
        result['system'][val] = getattr(uname, val)
    experiment_data = json.loads(ret.stdout.decode('utf-8'))
    for v in ['experiment', 'runtime']:
        result[v] = experiment_data[v]
    result_dir = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'json')
    with open('{}.json'.format(result_dir), 'w') as f:
        json.dump(result, f, indent = 2)
    
    run_timing = False
    # Dump results
    if run_timing:
        result = get_result_prefix(RESULTS_DIR, enabled_experiments['time']['name'])
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


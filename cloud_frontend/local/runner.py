import csv, gc, sys, imp, datetime, json, os, subprocess, uuid, sys

from distutils.dir_util import copy_tree
from utils import *

def get_language(lang):
    languages = {'python': 'python3', 'nodejs': 'nodejs'}
    return languages[lang]

def get_runner(experiment, options=None):
    runners = json.load(open('runners.json', 'r'))
    return runners[experiment][options] if options is not None else runners[experiment]

def get_runner_cmd(lang, experiment, options):
    executable = get_language(lang)
    script = get_runner(experiment, options)
    script_name, extension = os.path.splitext(script)
    # Out-of-proc measurements don't require languge-specific implementations
    if extension == '.py':
        executable = get_language('python')
    return [executable, script]

def export_storage_config(config):
    if config is not None:
        os.environ['MINIO_ADDRESS'] = config['address']
        os.environ['MINIO_ACCESS_KEY'] = config['access_key']
        os.environ['MINIO_SECRET_KEY'] = config['secret_key']

if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1], 'r'))
    input_data = cfg['input']
    repetitions = cfg['benchmark']['repetitions']
    experiment = cfg['benchmark']['type']
    language = cfg['benchmark']['language']
    export_storage_config(cfg['benchmark'].get('storage', None))
    experiment_options = cfg['benchmark'].get('experiment_options', None)

    # copy code to main directory
    copy_tree('code', '.')

    runner = get_runner_cmd(language, experiment, experiment_options)
    uuid = uuid.uuid1()
    ret = subprocess.run(runner + [sys.argv[1], str(uuid)], stdout=subprocess.PIPE)
    if ret.returncode != 0:
        print('Experiment finished incorrectly! Exit code {}'.format(ret.returncode))
        print('Output: ', ret.stdout.decode('utf-8'))
        sys.exit(1)

    # Dump experiment data
    result = {'input': cfg}
    try:
        experiment_data = json.loads(ret.stdout.decode('utf-8'))
        for v in ['experiment', 'runtime']:
            result[v] = experiment_data[v]
        result_dir = get_result_prefix(RESULTS_DIR, cfg['benchmark']['name'], 'json')
        with open(result_dir, 'w') as f:
            json.dump(result, f, indent = 2) 
    except json.decoder.JSONDecodeError as e:
        print('Experiment output is not valid!')
        print(e)
        print(ret.stdout.decode('utf-8'))
        sys.exit(1)

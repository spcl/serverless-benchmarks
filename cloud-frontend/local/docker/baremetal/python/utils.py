
import datetime, gc, platform, os, sys

from storage import minio_wrapper

RESULTS_DIR = 'results'
LOGS_DIR = 'logs'

def start_benchmarking(disable_gc):
    if disable_gc:
        gc.disable()
    return datetime.datetime.now()

def stop_benchmarking():
    end = datetime.datetime.now()
    gc.enable()
    return end

def get_result_prefix(dirname, name, suffix):
    import glob
    name = os.path.join(dirname, name)
    counter = 0
    while glob.glob( '{}_{:02d}*.{}'.format(name, counter, suffix) ):
        counter +=1
    return '{}_{:02d}'.format(name, counter)

def get_config():
    # get currently loaded modules
    # https://stackoverflow.com/questions/4858100/how-to-list-imported-modules
    modulenames = set(sys.modules) & set(globals())
    allmodules = [sys.modules[name] for name in modulenames]
    return {'name': 'python',
            'version': platform.python_version(),
            'modules': str(allmodules)}

def process_timestamps(timestamps):
    # convert list of lists of times data to proper timestamps
    return list(map(
        lambda times : list(map(
            lambda x: x.strftime('%s.%f'),
            times
        )),
        timestamps
    ))

def configure_client(config):
    minio_wrapper.create_instance(config)

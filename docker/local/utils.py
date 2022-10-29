import glob, os

RESULTS_DIR = 'results'
LOGS_DIR = 'logs'

def get_result_prefix(dirname, name, suffix):
    name = os.path.join(dirname, name)
    counter = 0
    while glob.glob( '{}_{:02d}*.{}'.format(name, counter, suffix) ):
        counter +=1
    return '{}_{:02d}.{}'.format(name, counter, suffix)

def process_timestamps(timestamps):
    # convert list of lists of times data to proper timestamps
    return list(map(
        lambda times : list(map(
            lambda x: x.strftime('%s.%f'),
            times
        )),
        timestamps
    ))

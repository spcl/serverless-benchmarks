import logging
import os
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PACK_CODE_APP = 'pack_code.sh'

def find(name, path):
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None

def create_output(dir, verbose):
    output_dir = os.path.abspath(dir)
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    os.chdir(output_dir)
    logging.basicConfig(
        filename='out.log',
        filemode='w',
        format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
        level=logging.DEBUG if verbose else logging.INFO
    )
    return output_dir

def find_benchmark(benchmark):
    benchmarks_dir = os.path.join(SCRIPT_DIR, '..', 'benchmarks')
    benchmark_path = find(benchmark, benchmarks_dir)
    if benchmark_path is None:
        logging.error('Could not find benchmark {} in {}'.format(args.benchmark, benchmarks_dir))
        sys.exit(1)
    return benchmark_path

def create_code_package(benchmark, benchmark_path, language, verbose):
    output = subprocess.run('{} -b {} -l {} {}'.format(
            os.path.join(SCRIPT_DIR, PACK_CODE_APP),
            benchmark_path, language,
            '-v' if verbose else ''
        ).split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logging.debug(output.stdout.decode('utf-8'))
    code_package = '{}.zip'.format(benchmark)
    # measure uncompressed code size with unzip -l
    ret = subprocess.run(['unzip -l {} | awk \'END{{print $1}}\''.format(code_package)], shell=True, stdout = subprocess.PIPE)
    if ret.returncode != 0:
        raise RuntimeError('Code size measurement failed: {}'.format(ret.stdout.decode('utf-8')))
    code_size = int(ret.stdout.decode('utf-8'))
    return code_package, code_size

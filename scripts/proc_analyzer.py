#!/usr/bin/env python3

import time, argparse, datetime, csv, json, subprocess, tempfile, os, operator, multiprocessing, threading

# Bottle server
import waitress, bottle
from bottle import route, run, request

class Measurements:

    def __init__(self, pids, output_dir):
        self._pids = pids
        self._pids_num = len(pids)
        self._output_dir = output_dir
        self._counter = 0
        self._data = []

    @property
    def data(self):
        return self._data


class MemoryMeasurements(Measurements):

    def __init__(self, pids, output_dir):
        super().__init__(pids, output_dir)
        smaps_files = ' '.join([
                ' /proc/{pid}/smaps '.format(pid=pid)
                for pid in self._pids
        ])
        self._copy_cmd = 'cat {smaps} > {output_dir}/smaps_{{id}}'.format(
                smaps=smaps_files,
                output_dir=output_dir
        )
        self._cached_cmd = 'cat /proc/meminfo | grep ^Cached: | awk \'{{print $2}}\''

    def measure(self):
        timestamp = datetime.datetime.now()
        ret = subprocess.run(
            '{copy} && {cached}'.format(
                    copy=self._copy_cmd.format(id=self._counter),
                    cached=self._cached_cmd
            ),
            stdout = subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        )
        self._counter += 1
        if ret.returncode != 0:
            print('Memory query failed!')
            print(ret.stderr.decode('utf-8'))
            raise RuntimeError()
        else:
            self._data.append([
                    timestamp.strftime('%s.%f'), 
                    self._pids_num,
                    int(ret.stdout.decode('utf-8').split('\n')[0])
                ])

    def postprocess(self):
        self._samples_counter = len(self._data)
        # Run awk over a file and sum RSS, PSS and Private mappings
        cmd = "awk \'/Rss:/{{ sum3 += $2 }} /Pss:/{{ sum += $2 }} "\
              "/Private/{{ sum2 += $2 }} END {{ print sum2, sum, sum3 }}\' "\
              "{dir}/smaps_{counter}"
        for i in range(0, self._samples_counter):
            ret = subprocess.run(
                    [cmd.format(dir=self._output_dir, counter=i)],
                    stdout = subprocess.PIPE, shell = True
                )
            # remove newline, seperate fields and convert into integers
            self._data[i].extend(
                    map(
                        int,
                        ret.stdout.decode('utf-8').strip().split()
                    )
            )

    @staticmethod
    def header():
        return ['Timestamp', 'N', 'Cached', 'USS', 'PSS', 'RSS']

class DiskIOMeasurements(Measurements):

    def __init__(self, pids, output_dir):
        if len(pids) > 1:
            raise NotImplementedError('DiskIOMeasurements does not support more than 1 PID!')
        super().__init__(pids, output_dir)
        self._cat_cmd = 'cat /proc/{pid}/io | awk \'{{print $2}}\''.format(pid=pids[0])

    def measure(self):
        timestamp = datetime.datetime.now()
        ret = subprocess.run(
                self._cat_cmd,
                stdout = subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell = True
            )
        if ret.returncode != 0:
            print('IO query failed!')
            print(ret.stderr.decode('utf-8'))
            raise RuntimeError()
        else:
            self._data.append(
                    [timestamp.strftime('%s.%f'), 1] +
                    list(map(int, ret.stdout.decode('utf-8').split('\n')[:-1]))
            )

    def postprocess(self):
        pass

    @staticmethod
    def header():
        return ['Timestamp', 'WriteChars', 'ReadChars', 'ReadSysCalls', 'WriteSysCalls', 'ReadBytes', 'WriteBytes']

# We use multiprocessing since we need a background worker that is active 100% time
# Multithreading does not work since server function never returns to handle new requests
# Queue is used to communicate results
class continuous_measurement:
    data_queue = multiprocessing.Queue()
    analyze = multiprocessing.Event()
    measure_func = None
    postprocess_func = None
    handler = None
    data = None

    def __init__(self, measurer_type, number_of_apps=1):
        self._measurer_type = measurer_type
        self._apps_number = number_of_apps
        self._pids = []
        self._processed_apps = 0
        self._finished_apps = 0
        #self.measure_func = functions['measure']
        #self.postprocess_func = functions['postprocess']

    def measure(self, pids, measurer_type):
        measurement_directory = tempfile.TemporaryDirectory()
        measurer_obj = measurer_type(pids, measurement_directory.name)
        try:
            samples_counter = 0
            while self.analyze.is_set():
                i = 0
                while i < 5:
                    #ret = self.measure_func(PID, samples_counter, self.measurement_directory)
                    measurer_obj.measure()

                    #if ret is None:
                    #    print('Measurements terminated!')
                    #    return
                    #self.data_queue.put(ret)
                    i += 1
                    #samples_counter += 1
            # in case we didn't get a measurement yet because the app finished too quickly
            #self.measure_func(PID, samples_counter, self.measurement_directory)
        except Exception as err:
            print('Failed!')
            print(err)
        finally:
            measurer_obj.postprocess()
            for val in measurer_obj.data:
                self.data_queue.put(val)
            self.data_queue.put('END')
            measurement_directory.cleanup()

    def start(self, req):
        uuid = req['uuid']
        self._pids.append(get_pid(uuid))
        if len(self._pids) == self._apps_number:
            # notify the start of measurement
            self.analyze.set()
            self.handler = multiprocessing.Process(target=self.measure, args=(self._pids, self._measurer_type))
            self.handler.start()
        else:
            self.analyze.wait()

    def stop(self, req):
        self._finished_apps += 1
        if self._finished_apps == self._apps_number:
            # notify the end of measurement
            self.analyze.clear()
            self.data = []
            # make sure that we get everything
            for v in iter(self.data_queue.get, 'END'):
                self.data.append(v)
        # wait for measurements to finish before ending
        self.handler.join()
        self._processed_apps = self._apps_number
    
    def get_data(self):
        #self.postprocess_func(self.data, self.measurement_directory)
        return self.data

    def cleanup(self):
        pass
        #self.measurement_directory.cleanup()

    @property
    def processed_apps(self):
        return self._finished_apps

# measure impact of running 1, 2, 3, ... N apps
class summary_measurement:
    all_instances_done = threading.Event()
    lock = threading.Lock()
    measurement_data = []
    number_of_apps = 0
    finished_apps = []
    measure_func = None
    postprocess_func = None

    def __init__(self, functions, number_of_apps):
        self.number_of_apps = number_of_apps
        #self.measure_func = functions['measure']
        #self.postprocess_func = functions['postprocess']

    def start(self, req):
        self.all_instances_done.clear()

    def stop(self, req):

        PID = get_pid(req['uuid'])
        PIDs = self.finished_apps + [PID]
        self.measurement_data.append(self.measure_func(PIDs))
        # This is intended to be used only by one process at a time.
        # However, we add lock for extension just to be sure it's safe.
        # Furthermore, modify collection after making measurements
        # Otherwise we might signal too early.
        self.lock.acquire()
        self.finished_apps = PIDs
        self.lock.release()

        if len(self.finished_apps) == self.number_of_apps:
            self.all_instances_done.set() 
        self.all_instances_done.wait()

    def get_data(self):
        return self.measurement_data

    def processed_apps(self):
        return len(self.finished_apps)
    
    def cleanup(self):
        pass

out_file = None

def get_pid(uuid):
    ret = subprocess.run('ps -fe | grep {}'.format(uuid), stdout=subprocess.PIPE, shell=True)
    PID = int(ret.stdout.decode('utf-8').split('\n')[0].split()[1])
    return PID

@route('/start', method='POST')
def start_analyzer():
    req = json.loads(request.body.read().decode('utf-8'))
    measurer.start(req)

@route('/stop', method='POST')
def stop_analyzer():
    req = json.loads(request.body.read().decode('utf-8'))
    measurer.stop(req)    

@route('/processed_apps', method='POST')
def processed_apps():
    return json.dumps({'apps' : measurer.processed_apps})

@route('/dump', method='POST')
def dump_data():

    # Background measurement launches a new process
    data = measurer.get_data()
    samples_counter = len(data)

    with open(out_file, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(metrics[args.metric].header())
        for val in data:
            csv_writer.writerow(val)

    measurer.cleanup()

metrics = { 'memory': MemoryMeasurements, 'disk-io': DiskIOMeasurements }

parser = argparse.ArgumentParser(description='Measure memory usage of processes.')
parser.add_argument('port', type=int, help='Port run')
parser.add_argument('output', type=str, help='Output file.')
parser.add_argument('metric', type=str, choices=['memory', 'disk-io'], help='Metric.')
parser.add_argument('apps', type=int, help='Number of apps that is expected')
args = parser.parse_args()
port = int(args.port)
out_file = args.output
number_of_apps = int(args.apps)
#if number_of_apps == 1:
#    measurers_functions = measurers[args.metric]['continuous']
#    measurer = continuous_measurement(measurers_functions, 1)
#else:
#    measurers_functions = measurers[args.metric]['summary']
#    measurer = summary_measurement(measurers_functions, number_of_apps)
measurer = continuous_measurement(metrics[args.metric], number_of_apps)
app = bottle.default_app()
print('Start at 0.0.0.0:{}'.format(port))
# listen on all ports
waitress.serve(app, host='0.0.0.0', port=port, threads=number_of_apps+1)

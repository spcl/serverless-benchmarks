#!/usr/bin/env python3

import time, argparse, datetime, csv, json, subprocess, tempfile, os, operator
from threading import Thread, Event
import gevent.monkey
gevent.monkey.patch_all()
from bottle import route, run, request

analyze = Event()
all_instances_done = Event()
out_file = None
data = []
number_of_apps = 0
finished_apps = []
measurement_directory = None
continuous_measurement_thread = None
samples_counter = 0

def measure(PID):
    global samples_counter
    timestamp = datetime.datetime.now()
    ret = subprocess.run(
            ['''
                cp /proc/{}/smaps {}/smaps_{} && cat /proc/meminfo | grep ^Cached: | awk \'{{print $2}}\'
            '''.format(PID, measurement_directory.name, samples_counter)],
            stdout = subprocess.PIPE, shell = True
        )
    data.append([
            timestamp.strftime('%s.%f'), 
            number_of_apps,
            int(ret.stdout.decode('utf-8').split('\n')[0])
        ])

def measure_now(PIDs):
    global finished_apps
    pids_set = set(PIDs)
    timestamp = datetime.datetime.now()
    ret = subprocess.run(
            ['''
                cat /proc/meminfo | grep ^Cached: | awk '{print $2}' && smem -c 'pid uss pss rss'
            '''],
            stdout = subprocess.PIPE, shell = True
        )

    #vals = []
    sums = [0]*3
    output = ret.stdout.decode('utf-8').split('\n')
    cached = int(output[0])
    print(pids_set)
    # smem does not have an ability to filter by process IDs, only process command
    for line in output[2:]:
        if line:
            vals = list(map(int, line.split()))
            if vals[0] in pids_set:
                sums = list(map(operator.add, sums, vals[1:]))
    data.append([
            timestamp.strftime('%s.%f'),
            len(PIDs),
            *sums
        ])
    finished_apps = PIDs
    if len(PIDs) == number_of_apps:
        all_instances_done.set() 
    all_instances_done.wait()

def measure_memory(PID):
    global samples_counter
    samples_counter = 0
    while analyze.is_set():
        i = 0
        while i < 5:
            measure(PID)
            i += 1
            samples_counter += 1
    # in case we didn't get a measurement yet because the app finished too quickly
    measure(PID)
    samples_counter += 1

@route('/start', method='POST')
def start_analyzer():
    global continuous_measurement_thread
    req = json.loads(request.body.read().decode('utf-8'))
    PID = req['PID']
    analyze.set()
    handler = Thread(target=measure_memory, args=(PID,))    
    continuous_measurement_thread = handler
    handler.start()

@route('/stop', method='POST')
def stop_analyzer():
    if number_of_apps == 1:
        analyze.clear()
        # wait for measurements to finish before ending
        continuous_measurement_thread.join()
    # measure impact of running 1, 2, 3, ... N apps
    else:
        req = json.loads(request.body.read().decode('utf-8'))
        measure_now(finished_apps + [req['PID']])
        #handler = Thread(target=measure_now, args=(finished_apps.copy(), ))
        #handler.start()

@route('/processed_apps', method='POST')
def processed_apps():
    return json.dumps({'apps' : len(finished_apps)})

@route('/dump', method='POST')
def dump_data():

    if measurement_directory is not None:
        for i in range(0, samples_counter):
            ret = subprocess.run(
                    ['''
                        awk \'/Shared/{{ sum += $2 }} /Private/{{ sum2 += 2 }} END {{ print sum2, sum }}\' {}/smaps_{}
                    '''.format(measurement_directory.name, i)],
                    stdout = subprocess.PIPE, shell = True
                )
            # remove newline and seperate into integers
            data[i].extend( map(int, ret.stdout.decode('utf-8').strip().split()) )
            data[i].extend( data[-1] + data[-2] )

    with open(out_file, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['Timestamp', 'N', 'Cached', 'USS', 'PSS/SSS', 'RSS'])
        for val in data:
            csv_writer.writerow(val)
    measurement_directory.cleanup()

parser = argparse.ArgumentParser(description='Measure memory usage of processes.')
parser.add_argument('port', type=int, help='Port run')
parser.add_argument('output', type=str, help='Output file.')
parser.add_argument('apps', type=int, help='Number of apps that is expected')
args = parser.parse_args()
port = int(args.port)
out_file = args.output
number_of_apps = args.apps
measurement_directory = tempfile.TemporaryDirectory()
run(host='0.0.0.0', server='gevent', port=port, debug=True)

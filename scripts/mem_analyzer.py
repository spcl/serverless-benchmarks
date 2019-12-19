#!/usr/bin/env python3

import time, argparse, datetime, csv, json
from threading import Thread, Event
from bottle import route, run, request

analyze = Event()
out_file = None
data = []

def measure_memory(PID):
    global handling
    while analyze.is_set():
        # sleep 0.5 ms - ideally we want to process every 1ms
        time.sleep(.0005)
        timestamp = datetime.datetime.now() 
        data.append([timestamp.strftime('%s.%f')])

@route('/start', method='POST')
def start_analyzer():
    req = json.loads(request.body.read().decode('utf-8'))
    PID = req['PID']
    analyze.set()
    handler = Thread(target=measure_memory, args=(PID,))    
    handler.start()

@route('/stop', method='POST')
def stop_analyzer():
    analyze.clear()

@route('/dump', method='POST')
def dump_data():
    with open(out_file, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['Timestamp', 'Cached', 'USS', 'PSS', 'RSS'])
        for val in data:
            csv_writer.writerow(val)

parser = argparse.ArgumentParser(description='Measure memory usage of processes.')
parser.add_argument('port', type=int, help='Port run')
parser.add_argument('output', type=str, help='Output file.')
args = parser.parse_args()
port = int(args.port)
out_file = args.output
run(host='0.0.0.0', port=port, debug=True)

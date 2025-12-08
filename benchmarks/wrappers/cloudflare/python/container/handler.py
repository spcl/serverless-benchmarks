#!/usr/bin/env python3
"""
Container handler for Cloudflare Workers - Python
This handler is used when deploying as a container worker
"""

import json
import sys
import os
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import datetime

# Monkey-patch requests library to add User-Agent header
# This is needed because many HTTP servers (like Wikimedia) reject requests without User-Agent
try:
    import requests
    original_request = requests.request
    
    def patched_request(method, url, **kwargs):
        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        if 'User-Agent' not in kwargs['headers']:
            kwargs['headers']['User-Agent'] = 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2'
        return original_request(method, url, **kwargs)
    
    requests.request = patched_request
    print("Monkey-patched requests library to add User-Agent header")
except ImportError:
    print("requests library not available, skipping User-Agent monkey-patch")

# Also patch urllib for libraries that use it directly
import urllib.request
original_urlopen = urllib.request.urlopen

def patched_urlopen(url, data=None, timeout=None, **kwargs):
    if isinstance(url, str):
        req = urllib.request.Request(url, data=data)
        req.add_header('User-Agent', 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2')
        return original_urlopen(req, timeout=timeout, **kwargs)
    elif isinstance(url, urllib.request.Request):
        if not url.has_header('User-Agent'):
            url.add_header('User-Agent', 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2')
        return original_urlopen(url, data=data, timeout=timeout, **kwargs)
    else:
        return original_urlopen(url, data=data, timeout=timeout, **kwargs)

urllib.request.urlopen = patched_urlopen
print("Monkey-patched urllib.request.urlopen to add User-Agent header")

# Import the benchmark handler function
from function import handler as benchmark_handler

# Import storage and nosql if available
try:
    import storage
except ImportError:
    storage = None
    print("Storage module not available")

try:
    import nosql
except ImportError:
    nosql = None
    print("NoSQL module not available")

PORT = int(os.environ.get('PORT', 8080))


class ContainerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()
    
    def do_POST(self):
        self.handle_request()
    
    def handle_request(self):
        # Handle favicon requests
        if 'favicon' in self.path:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'None')
            return
        
        try:
            # Extract Worker URL from header for R2 and NoSQL proxy
            worker_url = self.headers.get('X-Worker-URL')
            if worker_url:
                if storage:
                    storage.storage.set_worker_url(worker_url)
                if nosql:
                    nosql.nosql.set_worker_url(worker_url)
                print(f"Set worker URL for R2/NoSQL proxy: {worker_url}")
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''
            
            # Parse event from JSON body or URL params
            event = {}
            if body:
                try:
                    event = json.loads(body)
                except json.JSONDecodeError as e:
                    print(f'Failed to parse JSON body: {e}')
            
            # Parse URL parameters
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            for key, values in params.items():
                if key not in event and values:
                    value = values[0]
                    try:
                        event[key] = int(value)
                    except ValueError:
                        event[key] = value
            
            # Add request metadata
            import random
            req_id = str(random.randint(0, 1000000))
            income_timestamp = datetime.datetime.now().timestamp()
            event['request-id'] = req_id
            event['income-timestamp'] = income_timestamp
            
            print(f"!!! Event received: {json.dumps(event, default=str)}")
            print(f"!!! Event keys: {list(event.keys())}")
            print(f"!!! Event has 'bucket' key: {'bucket' in event}")
            if 'bucket' in event:
                print(f"!!! bucket value: {event['bucket']}")
            
            # Measure execution time
            begin = datetime.datetime.now().timestamp()
            
            # Call the benchmark function
            result = benchmark_handler(event)
            
            # Calculate timing
            end = datetime.datetime.now().timestamp()
            compute_time = end - begin
            
            # Prepare response matching native handler format exactly
            log_data = {
                'output': result['result']
            }
            if 'measurement' in result:
                log_data['measurement'] = result['measurement']
            
            response_data = {
                'begin': "0",
                'end': "0",
                'results_time': "0",
                'result': log_data,
                'is_cold': False,
                'is_cold_worker': False,
                'container_id': "0",
                'environ_container_id': "no_id",
                'request_id': "0"
            }
            
            # Send response
            if event.get('html'):
                # For HTML requests, return just the result
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                html_result = result.get('result', result)
                self.wfile.write(str(html_result).encode('utf-8'))
            else:
                # For API requests, return structured response
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
        
        except Exception as error:
            print(f'Error processing request: {error}')
            traceback.print_exc()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            error_response = {
                'error': str(error),
                'traceback': traceback.format_exc()
            }
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
    
    def log_message(self, format, *args):
        # Override to use print instead of stderr
        print(f"{self.address_string()} - {format % args}")


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), ContainerHandler)
    print(f'Container server listening on port {PORT}')
    server.serve_forever()

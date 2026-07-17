#!/usr/bin/env python3
"""
Container handler for Cloudflare Workers - Python
This handler is used when deploying as a container worker
"""

import json
import sys
import os
import traceback
import resource
import uuid
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

# Import the default benchmark handler function.
# For workflow dispatch mode, individual function modules are imported dynamically.
try:
    from function.function import handler as benchmark_handler
except ImportError:
    benchmark_handler = None

# Import storage and nosql if available
try:
    from function import storage
except ImportError:
    storage = None
    print("Storage module not available")

try:
    from function import nosql
except ImportError:
    nosql = None
    print("NoSQL module not available")

PORT = int(os.environ.get('PORT', 8080))


def probe_cold_start():
    is_cold = False
    fname = os.path.join("/tmp", "cold_run")
    if not os.path.exists(fname):
        is_cold = True
        container_id = str(uuid.uuid4())[0:8]
        with open(fname, "a") as f:
            f.write(container_id)
    else:
        with open(fname, "r") as f:
            container_id = f.read()

    return is_cold, container_id


def redis_header(headers, name, env_name, default=None):
    return headers.get(name) or os.getenv(env_name, default)


def write_workflow_measurement(headers, workflow_name, func_name, request_id, measurement):
    try:
        redis_host = redis_header(headers, "X-SEBS-REDIS-HOST", "REDIS_HOST", "")
        redis_username = redis_header(headers, "X-SEBS-REDIS-USERNAME", "REDIS_USERNAME")
        redis_password = redis_header(headers, "X-SEBS-REDIS-PASSWORD", "REDIS_PASSWORD")
        if redis_host:
            from redis import Redis

            redis_client = Redis(
                host=redis_host,
                port=6379,
                decode_responses=True,
                socket_connect_timeout=10,
                username=redis_username or None,
                password=redis_password or None,
            )
            key = os.path.join(workflow_name, func_name, request_id, str(uuid.uuid4())[0:8])
            redis_client.set(key, json.dumps(measurement))
    except Exception:
        pass


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
            # Get unique request ID from Cloudflare (CF-Ray header)
            req_id = self.headers.get('CF-Ray', str(uuid.uuid4()))
            os.environ["STORAGE_UPLOAD_BYTES"] = "0"
            os.environ["STORAGE_DOWNLOAD_BYTES"] = "0"
            
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
            
            # Workflow dispatch mode: if the event contains a "function" key,
            # route to that specific module instead of the default handler.
            if 'function' in event:
                import importlib
                func_name = event['function']
                func_input = event.get('input', {})
                workflow_request_id = (
                    self.headers.get("X-SEBS-Workflow-Request-ID") or req_id
                )
                workflow_name = (
                    self.headers.get("X-SEBS-Workflow-Name")
                    or os.getenv("WORKFLOW_NAME")
                    or os.getenv("BENCHMARK_NAME")
                    or "cloudflare-workflow"
                )
                if isinstance(func_input, dict):
                    func_input = {**func_input, 'request-id': req_id}
                start = datetime.datetime.now().timestamp()
                module = importlib.import_module(f"function.{func_name}")
                func_result = module.handler(func_input)
                end = datetime.datetime.now().timestamp()

                is_cold, container_id = probe_cold_start()
                measurement = {
                    "func": func_name,
                    "start": start,
                    "end": end,
                    "is_cold": is_cold,
                    "container_id": container_id,
                    "provider.request_id": req_id,
                }

                func_res = os.getenv("SEBS_FUNCTION_RESULT")
                if func_res:
                    measurement["result"] = json.loads(func_res)

                bytes_upload = os.getenv("STORAGE_UPLOAD_BYTES", 0)
                if bytes_upload:
                    measurement["blob.upload"] = int(bytes_upload)

                bytes_download = os.getenv("STORAGE_DOWNLOAD_BYTES", 0)
                if bytes_download:
                    measurement["blob.download"] = int(bytes_download)

                write_workflow_measurement(
                    self.headers,
                    workflow_name,
                    func_name,
                    workflow_request_id,
                    measurement,
                )
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(func_result).encode('utf-8'))
                return

            # Add request metadata
            income_timestamp = datetime.datetime.now().timestamp()
            event['request-id'] = req_id
            event['income-timestamp'] = income_timestamp

            # Measure execution time
            begin = datetime.datetime.now().timestamp()

            # Call the benchmark function
            result = benchmark_handler(event)
            
            # Calculate timing
            end = datetime.datetime.now().timestamp()
            compute_time = end - begin
            
            # Prepare response matching native handler format exactly
            log_data = {
                'result': result['result']
            }
            if 'measurement' in result:
                log_data['measurement'] = result['measurement']
            else:
                log_data['measurement'] = {}
            
            # Add memory usage to measurement
            memory_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            log_data['measurement']['memory_used_mb'] = memory_mb
            
            response_data = {
                'begin': begin,
                'end': end,
                'results_time': 0,
                'result': log_data,
                'is_cold': False,
                'is_cold_worker': False,
                'container_id': "0",
                'environ_container_id': "no_id",
                'request_id': req_id
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

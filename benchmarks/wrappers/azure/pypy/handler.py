import sys
import os
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import datetime
import uuid
import io

# Add current directory and handler directory to path to find function modules
# Similar to AWS handler which uses: sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))
current_dir = os.getcwd()
sys.path.append(current_dir)
handler_path = os.path.join(current_dir, 'handler')
if os.path.exists(handler_path):
    sys.path.insert(0, handler_path)
# Also add .python_packages like AWS does
python_packages_path = os.path.join(current_dir, '.python_packages', 'lib', 'site-packages')
if os.path.exists(python_packages_path):
    sys.path.append(python_packages_path)

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Initialize Storage/NoSQL if needed (Environment variables)
# Wrap in try-except to prevent crashes during initialization
try:
    if 'NOSQL_STORAGE_DATABASE' in os.environ:
        import nosql
        nosql.nosql.get_instance(
            os.environ['NOSQL_STORAGE_DATABASE'],
            os.environ['NOSQL_STORAGE_URL'],
            os.environ['NOSQL_STORAGE_CREDS']
        )
except Exception as e:
    logging.warning(f"Failed to initialize NoSQL: {e}")

try:
    if 'STORAGE_CONNECTION_STRING' in os.environ:
        import storage
        # Initialize storage instance
        storage.storage.get_instance(os.environ['STORAGE_CONNECTION_STRING'])
except Exception as e:
    logging.warning(f"Failed to initialize storage: {e}")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default logging, we'll handle it ourselves
        pass
    
    def handle_one_request(self):
        """Override to ensure we always send a response"""
        # Initialize response tracking before processing
        self._response_sent = False
        try:
            super().handle_one_request()
        except Exception as e:
            logging.error(f"Unhandled exception in handle_one_request: {e}", exc_info=True)
            # Try to send error response if not already sent
            if not self._response_sent:
                try:
                    error_body = json.dumps({'error': f'Unhandled exception: {str(e)}'}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Content-Length', str(len(error_body)))
                    self.end_headers()
                    self.wfile.write(error_body)
                    self.wfile.flush()
                    self._response_sent = True
                except Exception as e2:
                    logging.error(f"Failed to send error response in handle_one_request: {e2}", exc_info=True)
                    # Last resort: try to write directly
                    try:
                        if not self._response_sent:
                            self.wfile.write(b'{"error":"Internal server error"}')
                            self.wfile.flush()
                            self._response_sent = True
                    except:
                        pass
    
    def send_json_response(self, status_code, data):
        """Send a JSON response"""
        # Ensure response tracking is initialized
        if not hasattr(self, '_response_sent'):
            self._response_sent = False
        
        # Don't send if already sent
        if self._response_sent:
            logging.warning("Attempted to send response when already sent")
            return
            
        try:
            response_body = json.dumps(data).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self.send_header('Content-Length', str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            self.wfile.flush()
            self._response_sent = True
        except (BrokenPipeError, ConnectionResetError) as e:
            # Client disconnected, can't send response
            logging.warning(f"Client disconnected during response: {e}")
            self._response_sent = True
        except Exception as e:
            logging.error(f"Error in send_json_response: {e}", exc_info=True)
            # Try to send error response - check if headers were sent
            try:
                # Check if headers were already sent
                if hasattr(self, '_headers_buffer') and self._headers_buffer:
                    # Headers were sent, try to write error to body
                    error_msg = json.dumps({'error': f'Error sending response: {str(e)}'}).encode('utf-8')
                    self.wfile.write(error_msg)
                    self.wfile.flush()
                else:
                    # Headers not sent yet, send full error response
                    error_msg = json.dumps({'error': f'Error sending response: {str(e)}'}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Content-Length', str(len(error_msg)))
                    self.end_headers()
                    self.wfile.write(error_msg)
                    self.wfile.flush()
                self._response_sent = True
            except Exception as e2:
                # Can't write to response, mark as sent to prevent double error handling
                logging.error(f"Failed to send error response: {e2}", exc_info=True)
                # Last resort: try minimal response
                try:
                    if not self._response_sent:
                        self.wfile.write(b'{"error":"Internal server error"}')
                        self.wfile.flush()
                        self._response_sent = True
                except:
                    self._response_sent = True
    
    def do_GET(self):
        # Handle health checks and GET requests
        self.send_json_response(200, {'status': 'ok'})
    
    def do_POST(self):
        # Initialize response tracking before processing
        if not hasattr(self, '_response_sent'):
            self._response_sent = False
        # Wrap entire method to ensure we always send a response
        try:
            self._do_POST()
        except Exception as e:
            logging.error(f"Critical error in do_POST: {e}", exc_info=True)
            # Last resort - try to send error response
            if not self._response_sent:
                try:
                    error_body = json.dumps({'error': f'Critical error: {str(e)}'}).encode('utf-8')
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Content-Length', str(len(error_body)))
                    self.end_headers()
                    self.wfile.write(error_body)
                    self.wfile.flush()
                    self._response_sent = True
                except Exception as e2:
                    logging.error(f"Failed to send critical error response: {e2}", exc_info=True)
                    # Last resort: try to write minimal response
                    try:
                        if not self._response_sent:
                            self.wfile.write(b'{"error":"Internal server error"}')
                            self.wfile.flush()
                            self._response_sent = True
                    except:
                        pass
    
    def _do_POST(self):
        # Initialize response tracking
        self._response_sent = False
        req_json = None
        invocation_id = None
        begin = None
        
        try:
            logging.info(f"Received POST request to {self.path}")
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
            else:
                post_data = b'{}'
            
            try:
                req_json = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError as e:
                logging.error(f"JSON decode error: {e}, data: {post_data}")
                self.send_json_response(400, {'error': f'Invalid JSON: {str(e)}'})
                return

            invocation_id = self.headers.get('X-Azure-Functions-InvocationId', str(uuid.uuid4()))
            
            # Update request with ID (consistent with python wrapper)
            if isinstance(req_json, dict):
                req_json['request-id'] = invocation_id
                req_json['income-timestamp'] = datetime.datetime.now().timestamp()

            begin = datetime.datetime.now()
            
            # Import user function
            # In Azure, function.py is in the handler directory
            try:
                import function
            except ImportError as e:
                logging.error(f"Failed to import function: {e}")
                logging.error(f"sys.path: {sys.path}")
                logging.error(f"Current directory: {os.getcwd()}")
                logging.error(f"Handler path exists: {os.path.exists(os.path.join(os.getcwd(), 'handler'))}")
                # List files in handler directory for debugging
                handler_dir = os.path.join(os.getcwd(), 'handler')
                if os.path.exists(handler_dir):
                    try:
                        files = os.listdir(handler_dir)
                        logging.error(f"Files in handler directory: {files}")
                    except Exception as list_err:
                        logging.error(f"Failed to list handler directory: {list_err}")
                self.send_json_response(500, {'error': f'Failed to import function: {str(e)}'})
                return
            
            try:
                # Call the user function
                ret = function.handler(req_json)
            except Exception as e:
                logging.error(f"Function handler error: {e}", exc_info=True)
                self.send_json_response(500, {'error': str(e)})
                return
        except Exception as e:
            logging.error(f"Unexpected error in _do_POST: {e}", exc_info=True)
            if not self._response_sent:
                self.send_json_response(500, {'error': str(e)})
            return

        # Process response - wrap in try-except to ensure we always send a response
        try:
            end = datetime.datetime.now()

            # Logging and storage upload
            # Handle case where ret might be None or not a dict
            if ret is None:
                logging.error("Function handler returned None")
                self.send_json_response(500, {'error': 'Function handler returned None'})
                return
            
            if not isinstance(ret, dict):
                logging.warning(f"Function handler returned non-dict: {type(ret)}, value: {ret}")
                ret = {'result': ret}
            
            log_data = {
                'output': ret.get('result', ret) if isinstance(ret, dict) else ret
            }
            if isinstance(ret, dict) and 'measurement' in ret:
                log_data['measurement'] = ret['measurement']
            
            if req_json is not None and isinstance(req_json, dict) and 'logs' in req_json:
                log_data['time'] = (end - begin) / datetime.timedelta(microseconds=1)
                results_begin = datetime.datetime.now()
                try:
                    import storage
                    storage_inst = storage.storage.get_instance()
                    b = req_json.get('logs').get('bucket')
                    req_id = invocation_id
                    
                    storage_inst.upload_stream(b, '{}.json'.format(req_id),
                            io.BytesIO(json.dumps(log_data).encode('utf-8')))
                    
                    results_end = datetime.datetime.now()
                    results_time = (results_end - results_begin) / datetime.timedelta(microseconds=1)
                except Exception as e:
                    logging.warning(f"Failed to upload logs to storage: {e}")
                    results_time = 0
            else:
                results_time = 0

            # Cold start detection
            is_cold = False
            container_id = ''
            try:
                fname = os.path.join('/tmp','cold_run')
                if not os.path.exists(fname):
                    is_cold = True
                    container_id = str(uuid.uuid4())[0:8]
                    with open(fname, 'a') as f:
                        f.write(container_id)
                else:
                    with open(fname, 'r') as f:
                        container_id = f.read()
            except Exception as e:
                logging.warning(f"Failed to read/write cold_run file: {e}")
                container_id = str(uuid.uuid4())[0:8]
                    
            response_data = {
                'begin': begin.strftime('%s.%f'),
                'end': end.strftime('%s.%f'),
                'results_time': results_time,
                'result': log_data,
                'is_cold': is_cold,
                'container_id': container_id,
                'environ_container_id': os.environ.get('CONTAINER_NAME', ''),
                'request_id': invocation_id
            }

            # Send response
            self.send_json_response(200, response_data)
        except Exception as e:
            logging.error(f"Error processing response: {e}", exc_info=True)
            # Try to send error response
            try:
                self.send_json_response(500, {'error': f'Error processing response: {str(e)}'})
            except Exception as send_error:
                logging.error(f"Failed to send error response: {send_error}", exc_info=True)
                # Last resort - try to send minimal response
                try:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Internal server error'}).encode('utf-8'))
                    self.wfile.flush()
                except:
                    pass

def run(server_class=HTTPServer, handler_class=Handler):
    try:
        # Azure sets FUNCTIONS_CUSTOMHANDLER_PORT
        port = int(os.environ.get('FUNCTIONS_CUSTOMHANDLER_PORT', 8080))
        server_address = ('', port)
        httpd = server_class(server_address, handler_class)
        logging.info(f"Starting httpd on port {port}...")
        logging.info(f"Current directory: {os.getcwd()}")
        logging.info(f"Handler path: {os.path.join(os.getcwd(), 'handler')}")
        logging.info(f"Handler path exists: {os.path.exists(os.path.join(os.getcwd(), 'handler'))}")
        logging.info(f"sys.path: {sys.path}")
        # List files in current directory for debugging
        try:
            files = os.listdir(os.getcwd())
            logging.info(f"Files in current directory: {files}")
        except Exception as e:
            logging.warning(f"Failed to list current directory: {e}")
        httpd.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start server: {e}", exc_info=True)
        # Don't raise - try to log and exit gracefully
        sys.exit(1)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logging.info("Server interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


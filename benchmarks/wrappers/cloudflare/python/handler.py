import datetime, io, json, os, uuid, sys, ast
import asyncio
import importlib.util
import traceback
import time
try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    # Pyodide (Python native workers) doesn't support resource module
    HAS_RESOURCE = False
from workers import WorkerEntrypoint, Response
from js import fetch as js_fetch, URL

## sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))

"""
currently assumed file structure:

handler.py
function/
    function.py
    <other function files>.py
    storage.py
    nosql.py

"""

class Default(WorkerEntrypoint):
    async def fetch(self, request, env):
        try:
            return await self.fetch2(request, env)
        except Exception as e:
            t = traceback.format_exc()
            print(t)
            return Response(t)

    async def fetch2(self, request, env):
        if "favicon" in request.url: return Response("None")

        # Get unique request ID from Cloudflare (CF-Ray header)
        req_id = request.headers.get('CF-Ray', str(uuid.uuid4()))

        # Start timing measurements
        start = time.perf_counter()
        begin = datetime.datetime.now().timestamp()

        req_text = await request.text()

        event = json.loads(req_text) if len(req_text) > 0 else {}
        ## print(event)

        # dirty url parameters parsing, for testing
        tmp = request.url.split("?")
        if len(tmp) > 1:
            urlparams = tmp[1]
            urlparams = [chunk.split("=") for chunk in urlparams.split("&")]
            for param in urlparams:
                try:
                    event[param[0]] = int(param[1])
                except ValueError:
                    event[param[0]] = param[1]
                except IndexError:
                    event[param[0]] = None

        from function import storage

        storage.storage.init_instance(self)

        if hasattr(self.env, 'NOSQL_STORAGE_DATABASE'):
            from function import nosql

            nosql.nosql.init_instance(self)

        # Workflow dispatch mode: route to a specific function module
        if 'function' in event:
            import importlib
            func_name = event['function']
            func_input = event.get('input', {})
            if isinstance(func_input, dict):
                func_input = {**func_input, 'request-id': req_id}
            module = importlib.import_module(f"function.{func_name}")
            func_result = module.handler(func_input)
            return Response(json.dumps(func_result),
                            headers={"Content-Type": "application/json"})

        ## note: time fixed in worker
        income_timestamp = datetime.datetime.now().timestamp()

        event['request-id'] = req_id
        event['income-timestamp'] = income_timestamp


        print("event:", event)


##        make_benchmark_func()
##        function = import_from_path("function.function", "/tmp/function.py")

        from function import function

        ret = function.handler(event)

        log_data = {
            'result': ret['result']
        }
        if 'measurement' in ret:
            log_data['measurement'] = ret['measurement']
        else:
            log_data['measurement'] = {}

        # Add memory usage to measurement (if resource module is available)
        if HAS_RESOURCE:
            memory_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            log_data['measurement']['memory_used_mb'] = memory_mb
        else:
            # Pyodide doesn't support resource module
            log_data['measurement']['memory_used_mb'] = 0.0

        if 'logs' in event:
            log_data['time'] = 0

        if "html" in event:
            headers = {"Content-Type" : "text/html; charset=utf-8"}
            return Response(str(ret["result"]), headers = headers)
        else:
            # Trigger a fetch request to update the timer before measuring.
            # Cloudflare Workers freezes Date.now() and time.perf_counter() between
            # I/O operations as a timing-sidechannel mitigation. To record a meaningful
            # compute_time, we issue a throwaway self-fetch that triggers I/O and
            # unfreezes the clock before sampling the end time.
            try:
                # Fetch the worker's own URL with favicon to minimize overhead
                final_url = URL.new(request.url)
                final_url.pathname = '/favicon'
                await js_fetch(str(final_url), method='HEAD')
            except Exception:
                # Ignore fetch errors - this is a best-effort timer unfreeze
                pass
            
            # Calculate timestamps
            end = datetime.datetime.now().timestamp()
            elapsed = time.perf_counter() - start
            micro = elapsed * 1_000_000  # Convert seconds to microseconds
            
            # Cold start detection is not possible on Cloudflare Workers.
            # Unlike AWS Lambda or Azure Functions, Cloudflare does not provide
            # any API or mechanism to detect whether an invocation is a cold start.
            # The V8 isolate model used by Workers differs fundamentally from
            # container-based FaaS platforms - isolates can be reused across
            # requests but this reuse is not exposed to user code.
            # As a result, is_cold always returns False.
            return Response(json.dumps({
                'begin': begin,
                'end': end,
                'compute_time': micro,
                'results_time': 0,
                'result': log_data,
                'is_cold': False,
                'is_cold_worker': False,
                'container_id': "0",
                'environ_container_id': "no_id",
                'request_id': req_id
            }))

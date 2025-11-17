import datetime, io, json, os, uuid, sys, ast
import asyncio
import importlib.util
import traceback
from workers import WorkerEntrypoint, Response

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


def import_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


working_dir = os.path.dirname(__file__)

class MakeAsync(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        if node.name != "handler":
            return node
        return ast.AsyncFunctionDef(
            name=node.name,
            args=node.args,
            body=node.body,
            decorator_list=node.decorator_list,
            returns=node.returns,
            type_params=node.type_params)

class AddAwait(ast.NodeTransformer):
    to_find = ["upload_stream", "download_stream", "upload", "download", "download_directory"]
    
    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in self.to_find:
            #print(ast.dump(node.func, indent=2))
            return ast.Await(value=node)
        
        return node
        
def make_benchmark_func():
    with open(working_dir +"/function/function.py") as f:
        module = ast.parse(f.read())
    module = ast.fix_missing_locations(MakeAsync().visit(module))
    module = ast.fix_missing_locations(AddAwait().visit(module))
    new_source = ast.unparse(module)
    ##print("new_source:")
    ##print(new_source)
    ##print()
    with open("/tmp/function.py", "w") as wf:
        wf.write(new_source)
        

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






        ## we might need more data in self.env to know this ID
        req_id = 0
        ## note: time fixed in worker
        income_timestamp = datetime.datetime.now().timestamp()

        event['request-id'] = req_id
        event['income-timestamp'] = income_timestamp



        from function import storage

        storage.storage.init_instance(self)

        from function import nosql

        nosql.nosql.init_instance(self)



        print("event:", event)


##        make_benchmark_func()
##        function = import_from_path("function.function", "/tmp/function.py")

        from function import function
        
        ret = function.handler(event)

        log_data = {
            'output': ret['result']
        }
        if 'measurement' in ret:
            log_data['measurement'] = ret['measurement']
        if 'logs' in event:
            log_data['time'] = 0

        if "html" in event:
            headers = {"Content-Type" : "text/html; charset=utf-8"}
            return Response(str(ret["result"]), headers = headers)
        else:
            return Response(json.dumps({
                'begin': "0",
                'end': "0",
                'results_time': "0",
                'result': log_data,
                'is_cold': False,
                'is_cold_worker': False,
                'container_id': "0",
                'environ_container_id': "no_id",
                'request_id': "0"
            }))

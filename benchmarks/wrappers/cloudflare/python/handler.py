import datetime, io, json, os, uuid, sys

from workers import WorkerEntrypoint, Response

## sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))



class Default(WorkerEntrypoint):
    async def fetch(self, request, env):
        if "favicon" in request.url: return Response("None")
    
        req_text = await request.text()
        event = json.loads(req_text) if req_text is None else {}

        if True: # dirty url parameters parsing, for testing
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

        from storage import storage
        storage.init_instance(self)

        print("event:", event)

        from function import handler
        ret = handler(event)

        log_data = {
            'output': ret['result']
        }
        if 'measurement' in ret:
            log_data['measurement'] = ret['measurement']
        if 'logs' in event:
            log_data['time'] = 0

        if "html" in event:
            headers = {"Content-Type" : "text/html; charset=utf-8"}
            return Response(ret["result"], headers = headers)
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

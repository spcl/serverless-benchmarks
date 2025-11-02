import datetime, io, json, os, uuid, sys

from workers import WorkerEntrypoint, Response

## sys.path.append(os.path.join(os.path.dirname(__file__), '.python_packages/lib/site-packages'))



class Default(WorkerEntrypoint):
    async def fetch(self, request, env):
        req_json = await request.json()
        event = json.loads(req_json)

        ## we might need more data in self.env to know this ID
        req_id = 0
        ## note: time fixed in worker
        income_timestamp = datetime.datetime.now().timestamp()

        event['request-id'] = req_id
        event['income-timestamp'] = income_timestamp

        from . import storage
        storage.init_instance(self)


        from . import function
        ret = function.handler(event)

        log_data = {
            'output': ret['result']
        }
        if 'measurement' in ret:
            log_data['measurement'] = ret['measurement']
        if 'logs' in event:
            log_data['time'] = 0

        return Response(json.dumps({
            'begin': "0",
            'end': "0",
            'results_time': "0",
            'result': log_data,
            'is_cold': False,
            'is_cold_worker': False,
            'container_id': "0",
            'environ_container_id': os.environ['CONTAINER_NAME'],
            'request_id': "0"
        }))
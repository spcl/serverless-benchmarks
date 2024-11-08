import datetime, json, time

from . import misc
from . import queue
from . import storage
client = storage.storage.get_instance()


def handler(event):
    bucket = event['output_bucket']['name']
    file_count = int(event['file_count'])

    wait_begin = datetime.datetime.now()
    while (True):
        objs = client.list_objects(bucket, misc.object_path('extractors_output', ''))

        if (file_count == len(objs)):
            wait_end = datetime.datetime.now()
            orchestrator_input = {'bucket': {}}
            orchestrator_input['bucket']['name'] = bucket
            orchestrator_input['start_reducer'] = True
            orchestrator_input['parent_execution_id'] = event['request-id']

            queue_begin = datetime.datetime.now()
            queue_client = queue.queue(
                misc.function_name(
                    fname='orchestrator',
                    language='python',
                    version='3.9',
                    trigger='queue'
                )
            )
            queue_client.send_message(json.dumps(orchestrator_input))
            queue_end = datetime.datetime.now()

            wait_time = (wait_end - wait_begin) / datetime.timedelta(microseconds=1)
            queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
            return {
                'result': orchestrator_input,
                'fns_triggered': 1,
                'measurement': {
                    'wait_time': wait_time,
                    'queue_time': queue_time
                }
            }
        else:
            time.sleep(10)

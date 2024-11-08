import datetime, json, os

from . import misc
from . import queue

from . import nosql
nosql_client = nosql.nosql.get_instance()

nosql_table_name = 'flight_table'

# import boto3
# session = boto3.Session()
# dynamodb = session.resource('dynamodb')
# table = dynamodb.Table('flight_table')
  

def handler(event):
    if ('outbound_flight_id' not in event):
        raise ValueError('Invalid arguments')

    outbound_flight_id = event['outbound_flight_id']

    update_begin = datetime.datetime.now()
    # TODO: rewrite with generic nosql wrapper once it is merged
    # table.update_item(
    #     Key={"id": outbound_flight_id},
    #     ConditionExpression="id = :idVal AND seatCapacity > :zero",
    #     UpdateExpression="SET seatCapacity = seatCapacity - :dec",
    #     ExpressionAttributeValues={
    #         ":idVal": outbound_flight_id,
    #         ":dec": 1,
    #         ":zero": 0
    #     },
    # )
    update_end = datetime.datetime.now()

    reserve_booking_input = {
        'charge_id': event['charge_id'],
        'customer_id': event['customer_id'],
        'outbound_flight_id': outbound_flight_id,
        'parent_execution_id': event['request-id']
    }

    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='reserve_booking',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(reserve_booking_input))
    queue_end = datetime.datetime.now()

    update_time = (update_end - update_begin) / datetime.timedelta(microseconds=1)
    queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'fns_triggered': 1,
        'measurement': {
            'update_time': update_time,
            'queue_time': queue_time
        }
    }


"""
Sample input:
{
    "charge_id": "ch_1EeqlbF4aIiftV70qXHQewmn",
    "customer_id": "d749f277-0950-4ad6-ab04-98988721e475",
    "outbound_flight_id": "fae7c68d-2683-4968-87a2-dfe2a090c2d1"
}
"""
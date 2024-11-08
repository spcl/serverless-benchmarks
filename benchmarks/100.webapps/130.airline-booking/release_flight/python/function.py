import datetime, json, os

from . import misc

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
    #     Key={'id': outbound_flight_id},
    #     ConditionExpression='id = :idVal',# AND seatCapacity < maximumSeating',
    #     UpdateExpression='SET seatCapacity = seatCapacity + :dec',
    #     ExpressionAttributeValues={
    #         ':idVal': outbound_flight_id,
    #         ':dec': 1
    #     },
    # )
    update_end = datetime.datetime.now()

    update_time = (update_end - update_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'measurement': {
            'update_time': update_time
        }
    }

"""
Sample input:
{
    "outbound_flight_id": "fae7c68d-2683-4968-87a2-dfe2a090c2d1"
}
"""

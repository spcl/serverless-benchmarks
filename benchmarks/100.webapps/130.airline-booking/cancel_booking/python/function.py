import datetime, json, os

from . import misc
from . import queue

from . import nosql
nosql_client = nosql.nosql.get_instance()

nosql_table_name = 'booking_table'

# import boto3
# session = boto3.Session()
# dynamodb = session.resource('dynamodb')
# table = dynamodb.Table('booking_table')


def handler(event):
    """AWS Lambda Function entrypoint to cancel booking

    Parameters
    ----------
    event: dict, required
        Step Functions State Machine event

        chargeId: string
            pre-authorization charge ID

    context: object, required
        Lambda Context runtime methods and attributes
        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    -------
    boolean

    Raises
    ------
    BookingCancellationException
        Booking Cancellation Exception including error message upon failure
    """
    if ('booking_id' not in event):
        raise ValueError('Invalid booking ID')

    booking_id = event['booking_id']

    print(f'Cancelling booking - {booking_id}')
    update_begin = datetime.datetime.now()
    # TODO: rewrite with generic nosql wrapper once it is merged
    # ret = table.update_item(
    #     Key={'id': booking_id},
    #     ConditionExpression='id = :idVal',
    #     UpdateExpression='SET #STATUS = :cancelled',
    #     ExpressionAttributeNames={'#STATUS': 'status'},
    #     ExpressionAttributeValues={':idVal': booking_id, ':cancelled': 'CANCELLED'},
    # )
    update_end = datetime.datetime.now()

    release_flight_input = {
        'outbound_flight_id': event['outbound_flight_id'],
        'parent_execution_id': event['request-id']
    }

    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='release_flight',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(release_flight_input))
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
    "booking_id": "5347fc8e-46f2-434d-9d09-fa4d31f7f266",
    "outbound_flight_id": "fae7c68d-2683-4968-87a2-dfe2a090c2d1"
}
"""

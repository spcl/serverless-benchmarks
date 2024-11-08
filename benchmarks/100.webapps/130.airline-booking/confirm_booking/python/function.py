import datetime, json, os, secrets

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
    """AWS Lambda Function entrypoint to confirm booking

    Parameters
    ----------
    event: dict, required
        Step Functions State Machine event

        bookingId: string
            Unique Booking ID of an unconfirmed booking

    Returns
    -------
    string
        bookingReference generated
    """
    if ('booking_id' not in event):
        raise ValueError('Invalid booking ID')

    booking_id = event['booking_id']

    print(f'Confirming booking - {booking_id}')
    reference = secrets.token_urlsafe(4)
    update_begin = datetime.datetime.now()
    # TODO: rewrite with generic nosql wrapper once it is merged
    # ret = table.update_item(
    #     Key={'id': booking_id},
    #     ConditionExpression='id = :idVal',
    #     UpdateExpression='SET bookingReference = :br, #STATUS = :confirmed',
    #     ExpressionAttributeNames={'#STATUS': 'status'},
    #     ExpressionAttributeValues={
    #         ':br': reference,
    #         ':idVal': booking_id,
    #         ':confirmed': 'CONFIRMED',
    #     },
    #     ReturnValues='UPDATED_NEW',
    # )
    update_end = datetime.datetime.now()

    notify_booking_input = {
        'customer_id': event['customer_id'],
        'reference': reference,
        'parent_execution_id': event['request-id']
    }

    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='notify_booking',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(notify_booking_input))
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
    "customer_id": "d749f277-0950-4ad6-ab04-98988721e475",
    "booking_id": "5347fc8e-46f2-434d-9d09-fa4d31f7f266"
}
"""
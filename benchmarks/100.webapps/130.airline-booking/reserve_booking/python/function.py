import datetime, json, os, uuid

from . import misc
from . import queue

from . import nosql
nosql_client = nosql.nosql.get_instance()

nosql_table_name = 'booking_table'

# import boto3
# session = boto3.Session()
# dynamodb = session.resource('dynamodb')
# table = dynamodb.Table('booking_table')


def is_booking_request_valid(booking):
    return all(x in booking for x in ['outbound_flight_id', 'customer_id', 'charge_id'])

def handler(event):
    """AWS Lambda Function entrypoint to reserve a booking

    Parameters
    ----------
    event:
        chargeId: string
            Pre-authorization payment token

        customerId: string
            Customer unique identifier

        bookingOutboundFlightId: string
            Outbound flight unique identifier

    Returns
    -------
    bookingId: string
        booking ID generated
    """
    if (not is_booking_request_valid(event)):
        raise ValueError('Invalid booking request')

    print(f"Reserving booking for customer {event['customer_id']}")
    booking_id = str(uuid.uuid4())
    outbound_flight_id = event['outbound_flight_id']
    customer_id = event['customer_id']
    payment_token = event['charge_id']

    booking_item = {
        'id': booking_id,
        'bookingOutboundFlightId': outbound_flight_id,
        'checkedIn': False,
        'customer': customer_id,
        'paymentToken': payment_token,
        'status': 'UNCONFIRMED',
        'createdAt': str(datetime.datetime.now()),
    }
    update_begin = datetime.datetime.now()
    # table.put_item(Item=booking_item)
    nosql_client.insert(
        table_name=nosql_table_name,
        data=booking_item,
    )
    update_end = datetime.datetime.now()

    collect_payment_input = {
        'booking_id': booking_id,
        'customer_id': customer_id,
        'charge_id': payment_token,
        'outbound_flight_id': outbound_flight_id,
        'parent_execution_id': event['request-id']
    }

    queue_begin = datetime.datetime.now()
    queue_client = queue.queue(
        misc.function_name(
            fname='collect_payment',
            language='python',
            version='3.9',
            trigger='queue'
        )
    )
    queue_client.send_message(json.dumps(collect_payment_input))
    queue_end = datetime.datetime.now()

    update_time = (update_end - update_begin) / datetime.timedelta(microseconds=1)
    queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'fns_triggered': 1,
        'measurements': {
            'update_time': update_time,
            'queue_time': queue_time
        }
    }


"""
Sample input:
{
    "charge_id": "ch_1EeqlbF4aIiftV70qXHQewmn",
    "customer_id": "d749f277-0950-4ad6-ab04-98988721e475",
    "booking_id": "5347fc8e-46f2-434d-9d09-fa4d31f7f266",
    "outbound_flight_id": "fae7c68d-2683-4968-87a2-dfe2a090c2d1"
}
"""
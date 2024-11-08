import datetime, json, os

payment_endpoint = 'dummy'

from . import misc
from . import queue


def handler(event):
    """AWS Lambda Function entrypoint to collect payment

    Parameters
    ----------
    event: dict, required
        Step Functions State Machine event

        chargeId: string
            pre-authorization charge ID

    Returns
    -------
    dict
        receiptUrl: string
            receipt URL of charge collected

        price: int
            amount collected
    """
    if ('charge_id' not in event):
        raise ValueError('Invalid Charge ID')

    pre_authorization_token = event['charge_id']
    customer_id = event['customer_id']

    print(f'Collecting payment from customer {customer_id} using {pre_authorization_token} token')
    if (not payment_endpoint):
        raise ValueError('Payment API URL is invalid -- Consider reviewing PAYMENT_API_URL env')

    # This used to be an external API call:
    #
    # payment_payload = {'charge_id': charge_id}
    # ret = requests.post(payment_endpoint, json=payment_payload)
    # ret.raise_for_status()
    # payment_response = ret.json()

    if (payment_successful()):
        confirm_booking_input = {
            'customer_id': event['customer_id'],
            'booking_id': event['booking_id'],
            'parent_execution_id': event['request-id']
        }

        queue_begin = datetime.datetime.now()
        queue_client = queue.queue(
            misc.function_name(
                fname='confirm_booking',
                language='python',
                version='3.9',
                trigger='queue'
            )
        )
        queue_client.send_message(json.dumps(confirm_booking_input))
        queue_end = datetime.datetime.now()
    else:
        cancel_booking_input = {
            'outbound_flight_id': event['outbound_flight_id'],
            'booking_id': event['booking_id'],
            'parent_execution_id': event['request-id']
        }

        queue_begin = datetime.datetime.now()
        queue_client = queue.queue(
            misc.function_name(
                fname='cancel_booking',
                language='python',
                version='3.9',
                trigger='queue'
            )
        )
        queue_client.send_message(json.dumps(cancel_booking_input))
        queue_end = datetime.datetime.now()

    queue_time = (queue_end - queue_begin) / datetime.timedelta(microseconds=1)
    return {
        'result': 0,
        'fns_triggered': 1,
        'measurement': {
            'queue_time': queue_time
        }
    }

def payment_successful():
    return True # False


"""
Sample input:
{
    "charge_id": "ch_1EeqlbF4aIiftV70qXHQewmn",
    "customer_id": "d749f277-0950-4ad6-ab04-98988721e475",
    "booking_id": "5347fc8e-46f2-434d-9d09-fa4d31f7f266",
    "outbound_flight_id": "fae7c68d-2683-4968-87a2-dfe2a090c2d1"
}
"""
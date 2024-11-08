import datetime, json, os


def handler(event):
    """AWS Lambda Function entrypoint to notify booking

    Parameters
    ----------
    event: dict, required
        Step Functions State Machine event

        customer_id: string
            Unique Customer ID

        price: string
            Flight price

        bookingReference: string
            Confirmed booking reference

    context: object, required
        Lambda Context runtime methods and attributes
        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    -------
    string
        notificationId
            Unique ID confirming notification delivery

    Raises
    ------
    BookingNotificationException
        Booking Notification Exception including error message upon failure
    """
    if ('customer_id' not in event):
        raise ValueError('Invalid customer ID')

    customer_id = event['customer_id']
    booking_reference = event['reference']
    
    successful_subject = f'Booking confirmation for {booking_reference}'
    unsuccessful_subject = f'Unable to process booking'

    subject = successful_subject if booking_reference else unsuccessful_subject
    booking_status = 'confirmed' if booking_reference else 'cancelled'

    # Should we plan to support SNS-like cloud components in SeBS:
    #
    # payload = {'customerId': customer_id}
    # ret = sns.publish(
    #     TopicArn=booking_sns_topic,
    #     Message=json.dumps(payload),
    #     Subject=subject,
    #     MessageAttributes={
    #         'Booking.Status': {'DataType': 'String', 'StringValue': booking_status}
    #     },
    # )

    return {
        'result': 0,
        'measurement': {}
    }

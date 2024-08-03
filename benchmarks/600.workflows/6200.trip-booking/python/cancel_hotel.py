from . import nosql

nosql_client = nosql.nosql.get_instance()


def handler(event):

    trip_id = event["trip_id"]

    # Confirm flight
    nosql_table_name = "hotel_booking"
    booking_id = event["booking_id"]
    nosql_client.delete(nosql_table_name, ("trip_id", trip_id), ("booking_id", booking_id))

    return {"trip_id": trip_id, "status": "failure"}

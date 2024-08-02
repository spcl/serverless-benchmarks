from . import nosql

nosql_client = nosql.nosql.get_instance()


def handler(event):

    trip_id = event["trip_id"]

    # Confirm flight
    nosql_table_name = "flights"
    flight_id = event["flight_id"]
    nosql_client.delete(
        nosql_table_name,
        ("trip_id", trip_id),
        ("flight_id", flight_id)
    )

    return {"trip_id": trip_id}

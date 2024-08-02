from . import nosql

nosql_client = nosql.nosql.get_instance()


def handler(event):

    expected_result = event["expected_result"]
    if expected_result["result"] == "failure" and expected_result["reason"] == "confirm":
        raise RuntimeError("Failed to confirm the booking!")

    trip_id = event["trip_id"]

    # Confirm flight
    nosql_table_name = "flights"
    flight_id = event["flight_id"]
    nosql_client.update(
        nosql_table_name,
        ("trip_id", trip_id),
        ("flight_id", flight_id),
        {"status": "booked"},
    )

    return {"trip_id": trip_id}

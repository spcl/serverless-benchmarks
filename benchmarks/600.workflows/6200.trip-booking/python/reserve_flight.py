from . import nosql

nosql_client = nosql.nosql.get_instance()
nosql_table_name = "flights"


def handler(event):

    expected_result = event["expected_result"]
    if expected_result["result"] == "failure" and expected_result["reason"] == "flight":
        raise RuntimeError("Failed to book a flight!")

    # We start with the hotel
    trip_id = event["trip_id"]
    flight_id = event["request-id"]

    # Simulate return from a service
    flight_price = "1000"
    flight_connections = ["WAW"]
    flight_duration = "4h30m"

    nosql_client.insert(
        nosql_table_name,
        ("trip_id", trip_id),
        ("flight_id", flight_id),
        {
            **{key: event[key] for key in event.keys() if key.startswith("flight_")},
            "price": flight_price,
            "connections": flight_connections,
            "duration": flight_duration,
            "status": "pending",
        },
    )

    return {
        "trip_id": trip_id,
        "flight_id": flight_id,
        **{key: event[key] for key in ["booking_id", "rental_id"]},
        "expected_result": expected_result,
    }

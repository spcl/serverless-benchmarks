from . import nosql

nosql_client = nosql.nosql.get_instance()

nosql_table_name = "car_rentals"


def handler(event):

    expected_result = event["expected_result"]
    if expected_result["result"] == "failure" and expected_result["reason"] == "rental":
        raise RuntimeError("Failed to rent a car!")

    # We start with the hotel
    trip_id = event["trip_id"]
    rental_id = event["request-id"]

    # Simulate return from a service
    car_price = "125"
    car_name = "Fiat 126P"

    nosql_client.insert(
        nosql_table_name,
        ("trip_id", trip_id),
        ("rental_id", rental_id),
        {
            **{key: event[key] for key in event.keys() if key.startswith("rental_")},
            "rental_price": car_price,
            "rental_name": car_name,
            "status": "pending"
        },
    )

    return {
        "trip_id": trip_id,
        "rental_id": rental_id,
        **event
    }

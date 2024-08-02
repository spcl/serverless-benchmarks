import uuid
from . import nosql

nosql_client = nosql.nosql.get_instance()

nosql_table_name = "hotel_booking"


def handler(event):

    expected_result = event["expected_result"]
    if expected_result["result"] == "failure" and expected_result["reason"] == "hotel":
        raise RuntimeError("Failed to book the hotel!")

    # We start with the hotel
    trip_id = str(uuid.uuid4().hex)
    hotel_booking_id = event["request-id"]

    # Simulate return from a service
    hotel_price = "130"
    hotel_name = "BestEver Hotel"

    nosql_client.insert(
        nosql_table_name,
        ("trip_id", trip_id),
        ("booking_id", hotel_booking_id),
        {
            **{key: event[key] for key in event.keys() if key.startswith("hotel_")},
            "hotel_price": hotel_price,
            "hotel_name": hotel_name,
        },
    )

    return {"result": {"trip_id": trip_id, "booking_id": hotel_booking_id}}

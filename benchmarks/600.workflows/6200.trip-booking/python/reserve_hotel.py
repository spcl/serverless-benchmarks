import uuid

from . import nosql

nosql_client = nosql.nosql.get_instance()
nosql_table_name = "hotel_booking"

def _get_request_id(event):
    request_id = event.get("request-id") or event.get("request_id") or event.get("requestId")
    if not request_id:
        request_id = uuid.uuid4().hex
    event["request-id"] = request_id
    return request_id


def handler(event):

    expected_result = event["expected_result"]
    if expected_result["result"] == "failure" and expected_result["reason"] == "hotel":
        raise RuntimeError("Failed to book the hotel!")

    # We start with the hotel
    trip_id = str(uuid.uuid4().hex)
    hotel_booking_id = _get_request_id(event)

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
            "status": "pending",
        },
    )

    return {"trip_id": trip_id, "booking_id": hotel_booking_id, **event}

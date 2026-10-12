# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.


def allocate_nosql() -> dict:

    return {
        "flights": {
            "primary_key": "trip_id",
            "secondary_key": "flight_id"
        },
        "car_rentals": {
            "primary_key": "trip_id",
            "secondary_key": "rental_id"
        },
        "hotel_booking": {
            "primary_key": "trip_id",
            "secondary_key": "booking_id"
        }
    }

def generate_input(
    data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func
):

    input_config = {}

    # test - invoke a single trip, succeed
    # small - fail in the middle
    # large - fail at the last step

    trip_details = {
        "flight_depart": "ZRH",
        "flight_arrive": "KTW",
        "flight_date": "2020-08-22T13:00:00",
        "hotel_stars": "3",
        "hotel_nights": "3",
        "hotel_distance": "1500",
        "hotel_price_max": "150",
        "rental_class": "compact",
        "rental_price_max": "100",
        "rental_duration": 3,
        "rental_requests": ["full_tank", "CDW", "assistance"]
    }

    size_results = {
        "test": {"result": "success"},
        "small": {"result": "failure", "reason": "hotel"},
        "large": {"result": "failure", "reason": "confirm"}
    }
    trip_details["expected_result"] = size_results[size]

    return trip_details


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage=None) -> str | None:

    if output is None:
        return "Output is None"

    if not isinstance(output, dict):
        return f"Expected output to be a dict, got {type(output).__name__}"

    if "trip_id" not in output:
        return "Output is missing 'trip_id' field"

    if not isinstance(output["trip_id"], str) or not output["trip_id"]:
        return "Output 'trip_id' must be a non-empty string"

    if "status" not in output:
        return "Output is missing 'status' field"

    if not isinstance(output["status"], str):
        return f"Output 'status' must be a string, got {type(output['status']).__name__}"

    expected_result = input_config.get("expected_result", {})
    expected_outcome = expected_result.get("result")
    expected_reason = expected_result.get("reason")

    valid_statuses = {"success", "failure"}
    if output["status"] not in valid_statuses:
        return f"Output 'status' must be one of {valid_statuses}, got '{output['status']}'"

    # trip_id is a UUID stored without dashes (32 hex chars)
    import re
    if not re.match(r'^[0-9a-f]{32}$', output["trip_id"], re.IGNORECASE):
        return f"Output 'trip_id' is not a 32-char hex UUID: '{output['trip_id']}'"

    if expected_outcome == "success":
        if output["status"] != "success":
            return f"Expected status 'success', got '{output['status']}'"

    elif expected_outcome == "failure":
        if expected_reason == "hotel":
            # Hotel failure raises RuntimeError immediately, so the workflow fails
            # with an exception. If validate_output is called, the framework caught
            # it gracefully - accept any status in this case.
            pass
        elif expected_reason in ["confirm", "rental", "flight"]:
            if output["status"] != "failure":
                return f"Expected status 'failure' (reason: {expected_reason}), got '{output['status']}'"

    return None

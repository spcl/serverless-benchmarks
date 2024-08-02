
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

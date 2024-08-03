from . import nosql

nosql_client = nosql.nosql.get_instance()


def handler(event):

    trip_id = event["trip_id"]

    # Confirm flight
    nosql_table_name = "car_rentals"
    rental_id = event["rental_id"]
    nosql_client.delete(nosql_table_name, ("trip_id", trip_id), ("rental_id", rental_id))

    event.pop("rental_id")
    return event

import uuid

def allocate_nosql() -> dict:
    return {"shopping_cart": {"primary_key": "cart_id", "secondary_key": "product_id"}}


def generate_input(
    data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func
):

    input_config = {}

    cart_id = str(uuid.uuid4().hex)

    nosql_func(
        "130.crud-api",
        "shopping_cart",
        {"name": "Gothic Game", "price": 42, "quantity": 2},
        ("cart_id", cart_id),
        ("product_id", "game-gothic"),
    )

    requests = []

    if size == "test":
        # create a single entry
        requests.append(
            {
                "route": "GET /cart/{id}",
                "path": {"id": "game-gothic"},
                "body": {
                    "cart": cart_id,
                },
            }
        )
    elif size == "small":
        pass
    elif size == "large":
        # add few entries, query and return avg
        pass

    input_config["requests"] = requests

    return input_config

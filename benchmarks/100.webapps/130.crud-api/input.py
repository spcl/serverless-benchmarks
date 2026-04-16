# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import uuid


def allocate_nosql() -> dict:
    return {"shopping_cart": {"primary_key": "cart_id", "secondary_key": "product_id"}}


def generate_input(
    data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_upload
):

    input_config = {}

    cart_id = str(uuid.uuid4().hex)
    write_cart_id = str(uuid.uuid4().hex)

    # Set initial data

    nosql_upload(
        "130.crud-api",
        "shopping_cart",
        {"name": "Gothic Game", "price": 42, "quantity": 2},
        ("cart_id", cart_id),
        ("product_id", "game-gothic"),
    )
    nosql_upload(
        "130.crud-api",
        "shopping_cart",
        {"name": "Gothic 2", "price": 142, "quantity": 3},
        ("cart_id", cart_id),
        ("product_id", "game-gothic-2"),
    )
    nosql_upload(
        "130.crud-api",
        "shopping_cart",
        {"name": "SeBS Benchmark", "price": 1000, "quantity": 1},
        ("cart_id", cart_id),
        ("product_id", "sebs-benchmark"),
    )
    nosql_upload(
        "130.crud-api",
        "shopping_cart",
        {"name": "Mint Linux", "price": 0, "quantity": 5},
        ("cart_id", cart_id),
        ("product_id", "mint-linux"),
    )

    requests = []

    if size == "test":
        # retrieve a single entry
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
        requests.append(
            {
                "route": "GET /cart",
                "body": {
                    "cart": cart_id,
                },
            }
        )
    elif size == "large":
        # add many new entries
        for i in range(5):
            requests.append(
                {
                    "route": "PUT /cart",
                    "body": {
                        "cart": write_cart_id,
                        "product_id": f"new-id-{i}",
                        "name": f"Test Item {i}",
                        "price": 100 * i,
                        "quantity": i,
                    },
                }
            )
            requests.append(
                {
                    "route": "GET /cart",
                    "body": {
                        "cart": write_cart_id,
                    },
                }
            )

    input_config["requests"] = requests
    input_config["size"] = size

    return input_config

def validate_output(input_config: dict, output: dict) -> bool:
    results = output.get('result', [])
    requests = input_config.get('requests', [])
    size = input_config.get('size', '')
    if not isinstance(results, list) or len(results) != len(requests):
        return False

    # Track the expected number of items in the cart for 'large' PUT/GET sequences.
    put_count = 0

    for request, result in zip(requests, results):
        route = request.get('route')
        if route == 'GET /cart/{id}':
            expected_id = request.get('path', {}).get('id', '')
            if expected_id == 'game-gothic':
                if result.get('name') != 'Gothic Game':
                    return False
                if result.get('price') != 42:
                    return False
                if result.get('quantity') != 2:
                    return False
            elif not ('name' in result and 'price' in result and 'quantity' in result):
                return False
        elif route == 'GET /cart':
            products = result.get('products')
            if not isinstance(products, list) or len(products) == 0:
                return False
            if 'total_cost' not in result:
                return False
            if size == 'small':
                # 4 pre-inserted products; total_cost is the sum of their prices.
                if len(products) != 4:
                    return False
                if result.get('total_cost') != 42 + 142 + 1000 + 0:
                    return False
            elif size == 'large':
                # Each GET follows a PUT, so the list grows by one each time.
                if len(products) != put_count:
                    return False
        elif route == 'PUT /cart':
            if result != {}:
                return False
            put_count += 1
    return True

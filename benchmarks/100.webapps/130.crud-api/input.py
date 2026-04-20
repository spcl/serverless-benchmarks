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

def validate_output(input_config: dict, output: dict, language: str, architecture: str, storage = None) -> str | None:

    results = output.get('result', [])
    requests = input_config.get('requests', [])

    if not isinstance(results, list):
        return f"Output results is not a list (type={type(results).__name__})"

    if len(results) != len(requests):
        return f"Results count mismatch: expected {len(requests)} responses but got {len(results)}"

    if len(results) == 1:
        """
            test input -> one result for a single cart item
            small input -> one result for entire cart
        """
        request = requests[0]
        result = results[0]
        route = request.get('route')

        if route == 'GET /cart/{id}':

            expected_item = {"name": "Gothic Game", "price": 42, "quantity": 2}
            expected_item["cart_id"] = request["body"]["cart"]
            expected_item["product_id"] = request["path"]["id"]

            if expected_item != result:
                return f"Wrong item details for GET /cart/{{id}}: expected {expected_item} but got {result}"

        elif route == 'GET /cart':

            products = [
                ("Gothic Game", 42, 2),
                ("Gothic 2", 142, 3),
                ("SeBS Benchmark", 1000, 1),
                ("Mint Linux", 0, 5)
            ]
            total_cost = sum([p[1] * p[2] for p in products])
            items = sum([p[2] for p in products])
            cart = [p[0] for p in products]

            if sorted(cart) != sorted(result['products']):
                return f"Wrong product details for GET /cart: expected {cart} but got {result['products']}"

            if total_cost != result['total_cost']:
                return f"Wrong product details for GET /cart: expected {total_cost}, but got {result['total_cost']}"

            if abs(total_cost / items - result['avg_price']) > 1e-6:
                return f"Wrong product details for GET /cart: expected {total_cost/items}, but got {result['products']}"
        else:
            return f"Unexpected route in single-result output: expected 'GET /cart/{{id}}' or 'GET /cart' but got '{route}'"
    else:
        """
            large input -> 10 responses, 
        """

        put_results = results[0::2]
        get_results = results[1::2]

        for put_result in put_results:
            if put_result != {}:
                return f"PUT /cart expected empty dict {{}} but got {put_result}"

        current_cost = 0
        current_quantity = 0
        items = []
        for idx, get_result in enumerate(get_results):

            items.append(f"Test Item {idx}")
            current_cost += 100 * idx * idx
            current_quantity += idx

            if get_result['products'] != items:
                return f"Wrong product details for GET /cart: expected {items} but got {get_result['products']}"

            if current_cost != get_result['total_cost']:
                return f"Wrong product details for GET /cart: expected {current_cost}, but got {get_result['total_cost']}"

            if current_quantity == 0:
                continue

            if abs(current_cost / current_quantity - get_result['avg_price']) > 1e-6:
                return f"Wrong product details for GET /cart: expected {current_cost/current_quantity}, but got {get_result['products']}"

    return None

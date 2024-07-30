from . import nosql
import os
nosql_client = nosql.nosql.get_instance()

def handler(event):

    table = "shopping_cart"

    nosql_client.insert(
        table,
        ("cart_id", "new_tmp_cart"),
        ("product_id", event['request-id']),
        {"price": 10, "quantity": 1}
    )

    res = nosql_client.query(
        table,
        ("cart_id", "new_tmp_cart"),
        "product_id",
    )

    return {
        "result": {
            "queries": res
        }
    }

import os

from . import nosql

nosql_client = nosql.nosql.get_instance()

nosql_table_name = "shopping_cart"

def add_product(card_id: str, product_id: str, product_name: str, price: float, quantity: int):

    nosql_client.insert(
        table,
        ("cart_id", card_id),
        ("product_id", product_id),
        {"price": 10, "quantity": 1}
    )

def get_products():
    pass

def query_items():
    pass

def handler(event):


    for request in event:

        route = request['route']

        if route == "PUT /cart":
            add_product()

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

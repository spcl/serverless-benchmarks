
def buckets_count():
    return (0, 0)

def allocate_nosql() -> dict:
    return {
        'shopping_cart': {
            'primary_key': 'cart_id',
            'secondary_key': 'product_id'
        }
    }

def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func):

    input_config = {}
    return input_config

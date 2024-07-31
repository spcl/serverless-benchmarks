
url_generators = {
    # source: mlperf fake_imagenet.sh. 230 kB
    'test' : 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Jammlich_crop.jpg/800px-Jammlich_crop.jpg',
    # video: HPX source code, 6.7 MB
    'small': 'https://github.com/STEllAR-GROUP/hpx/archive/refs/tags/1.4.0.zip',
    # resnet model from pytorch. 98M
    'large':  'https://download.pytorch.org/models/resnet50-19c8e357.pth'
}

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

    requests = []

    if size == "test":
        # create a single entry
    elif size == "small":
        # 
    elif size == "large":
        # add few entries, query and return avg

    input_config["requests"] = requests

    return input_config

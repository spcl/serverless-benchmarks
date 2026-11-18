# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import os

# Upstream response delay (ms) and response size (bytes) per input size.
size_generators = {
    'test': (10, 2048),
    'small': (200, 16384),
    'large': (1000, 262144),
}


def upstream_url():
    url = os.environ.get('SEBS_MOCK_UPSTREAM')
    if not url:
        raise RuntimeError(
            'Set SEBS_MOCK_UPSTREAM to the URL of the mock upstream service '
            'that the functions can reach (see README.md of this benchmark).'
        )
    return url


def buckets_count():
    return (0, 0)


def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    latency_ms, response_size = size_generators[size]
    return {
        'upstream': upstream_url(),
        'latency_ms': latency_ms,
        'size': response_size,
        'seed': 1,
        'limit': 10,
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    result = output.get('result', {})
    items = result.get('items')
    if not isinstance(items, list) or not 0 < len(items) <= input_config.get('limit', 10):
        return f"Expected between 1 and {input_config.get('limit', 10)} items, got {items!r:.200}"
    ratings = [item.get('rating') for item in items]
    if ratings != sorted(ratings, reverse=True):
        return "Items are not sorted by rating"
    measurement = output.get('measurement', {})
    if measurement.get('upstream_wait_us', 0) < input_config['latency_ms'] * 1000:
        wait = measurement.get('upstream_wait_us')
        return f"Upstream wait {wait} us is shorter than the configured latency"
    return None

# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import os

# Upstream response delay (ms) and page size (bytes) per input size.
size_generators = {
    'test': (10, 20000),
    'small': (200, 200000),
    'large': (1000, 2000000),
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
    latency_ms, page_size = size_generators[size]
    return {
        'upstream': upstream_url(),
        'latency_ms': latency_ms,
        'size': page_size,
        'seed': 1,
        'max_length': 5000,
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    result = output.get('result', {})
    content = result.get('content', '')
    if not isinstance(content, str) or not content.startswith('# Benchmark article'):
        return f"Content does not start with the article title: {content[:100]!r}"
    if len(content) > input_config.get('max_length', 5000):
        return f"Content is longer than max_length: {len(content)}"
    if '<script' in content or 'analytics' in content:
        return "Page boilerplate (scripts) leaked into the markdown"
    measurement = output.get('measurement', {})
    if measurement.get('upstream_wait_us', 0) < input_config['latency_ms'] * 1000:
        wait = measurement.get('upstream_wait_us')
        return f"Upstream wait {wait} us is shorter than the configured latency"
    return None

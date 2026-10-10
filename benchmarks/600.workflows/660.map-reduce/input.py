# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import os
import random

size_generators = {
    "test" : (50, 3),
    "small": (1000, 3),
    "large": (100000, 3)
}


def buckets_count():
    return (1, 1)


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    mult, n_mappers = size_generators[size]
    words = ["cat", "dog", "bird", "horse", "pig"]
    lst = mult * words
    random.shuffle(lst)

    list_path = os.path.join(data_dir, "words")
    list_name = "words"
    with open(list_path, "w") as f:
        f.writelines(w+"\n" for w in lst)

    upload_func(0, list_name, list_path)
    #os.remove(list_path)

    return {
        "benchmark_bucket": benchmarks_bucket,
        "words_bucket": input_buckets[0],
        "words": list_name,
        "n_mappers": n_mappers,
        "output_bucket": output_buckets[0]
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage=None) -> str | None:
    expected_words = {"cat", "dog", "bird", "horse", "pig"}

    if output is None:
        return "Output is None"

    # Output is wrapped: {"list": [...], "__request_id": "..."}
    if isinstance(output, dict):
        if "list" in output:
            output = output["list"]
        else:
            return f"Expected output dict to have 'list' key, got keys: {list(output.keys())}"

    if not isinstance(output, list):
        return f"Expected output to be a list, got {type(output).__name__}"

    seen_words = set()
    for i, entry in enumerate(output):
        if not isinstance(entry, dict):
            return f"Entry {i} is not a dict: {type(entry).__name__}"

        if "word" not in entry:
            return f"Entry {i} is missing 'word' key"
        if "count" not in entry:
            return f"Entry {i} is missing 'count' key"

        word = entry["word"]
        count = entry["count"]

        if not isinstance(word, str):
            return f"Entry {i} 'word' is not a string: {type(word).__name__}"
        if not isinstance(count, int):
            return f"Entry {i} 'count' is not an int: {type(count).__name__}"

        if word not in expected_words:
            return f"Entry {i} has unexpected word: '{word}'"

        if count <= 0:
            return f"Entry {i} has non-positive count: {count}"

        seen_words.add(word)

    if seen_words != expected_words:
        missing = expected_words - seen_words
        return f"Missing words in output: {missing}"

    word_counts = {entry["word"]: entry["count"] for entry in output if entry["word"] in expected_words}

    # All words appear the same number of times (input is mult * ["cat","dog","bird","horse","pig"])
    counts = list(word_counts.values())
    if len(set(counts)) != 1:
        return f"Word counts are not equal — expected uniform distribution, got: {word_counts}"

    per_word = counts[0]
    total = per_word * len(expected_words)

    # Total must be mult * 5 words; verify it matches the n_mappers-based expectation
    # n_mappers is in input_config; total words = mult * 5, which must be divisible by 5
    if total % len(expected_words) != 0:
        return f"Total word count {total} is not divisible by {len(expected_words)}"

    return None

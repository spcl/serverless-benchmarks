# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import base64
import random

size_generators = {
    "test" : 10,
    "small": 100,
    "large": 1000
}


def buckets_count():
    return (0, 0)


def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    mult = size_generators[size]
    msg = "Who let the dogs out?\n" * mult

    return {
        "message": msg,
        "token": "allow"
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    if "response" not in output:
        return "Missing 'response' key in output"

    response = output["response"]

    if response == "unauthorized":
        return "Response is 'unauthorized', expected encrypted message"

    try:
        decoded = base64.b64decode(response)
    except Exception as e:
        return f"Response is not a valid base64 string: {e}"

    message = input_config["message"]
    expected_length = len(message)
    if len(decoded) != expected_length:
        return (
            f"Decoded ciphertext length ({len(decoded)}) does not match "
            f"input message length ({expected_length})"
        )

    # Decrypt and verify the ciphertext matches the original plaintext.
    # The handler uses AES-CTR with a fixed key and counter starting at 0.
    import pyaes
    KEY = "6368616e676520746869732070617373".encode("utf-8")
    counter = pyaes.Counter(initial_value=0)
    aes = pyaes.AESModeOfOperationCTR(KEY, counter=counter)
    decrypted = aes.decrypt(decoded)
    if isinstance(message, str):
        message_bytes = message.encode("utf-8")
    else:
        message_bytes = message
    if decrypted != message_bytes:
        return "Decrypted ciphertext does not match original input message"

    return None

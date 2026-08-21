# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.


def buckets_count():
    return (0, 0)


def generate_input(data_dir, size, bucket, input_buckets, output_buckets, upload_func, nosql_func):
    return dict()


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage=None) -> str | None:
    if output is None:
        return "Output is None"

    if "done" not in output or output["done"] is not True:
        return "Expected 'done' key to be True"

    if "astros" not in output:
        return "Missing 'astros' key in output"

    # Output structure: output["astros"] is a dict with nested output["astros"]["astros"]["people"]
    astros_outer = output["astros"]
    if isinstance(astros_outer, dict):
        inner = astros_outer.get("astros", {})
        people = inner.get("people", []) if isinstance(inner, dict) else []
    elif isinstance(astros_outer, list):
        people = astros_outer
    else:
        return f"'astros' has unexpected type: {type(astros_outer).__name__}"

    if not isinstance(people, list):
        return f"Expected people to be a list, got {type(people).__name__}"

    # The API response includes number and message at the inner astros level
    if isinstance(astros_outer, dict):
        inner = astros_outer.get("astros", {})
        if isinstance(inner, dict):
            api_message = inner.get("message")
            if api_message != "success":
                return f"API 'message' field is '{api_message}', expected 'success'"
            api_number = inner.get("number")
            if api_number is not None and api_number != len(people):
                return f"API 'number' field is {api_number} but people list has {len(people)} entries"

    for i, person in enumerate(people):
        if not isinstance(person, dict):
            return f"Element {i} is not a dict"
        if "name" not in person:
            return f"Element {i} missing 'name' field"
        if "name_rev" not in person:
            return f"Element {i} missing 'name_rev' field"

        name = person["name"]
        name_rev = person["name_rev"]

        if not isinstance(name, str) or not name.strip():
            return f"Element {i} 'name' must be a non-empty string"
        if not isinstance(name_rev, str) or not name_rev.strip():
            return f"Element {i} 'name_rev' must be a non-empty string"

        # name_rev splits on first space only: "First Last" -> "Last First"
        parts = name.split(" ", 1)
        expected_rev = " ".join(reversed(parts))
        if name_rev != expected_rev:
            return f"Element {i} 'name_rev' is '{name_rev}', expected '{expected_rev}'"

        if "craft" not in person or not isinstance(person["craft"], str) or not person["craft"]:
            return f"Element {i} missing or empty 'craft' field"

    return None

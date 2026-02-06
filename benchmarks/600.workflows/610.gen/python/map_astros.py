def handler(elem):
    name = elem["name"]
    parts = name.split()
    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]
        elem["name_rev"] = f"{last} {first}"
    else:
        elem["name_rev"] = name
    return elem

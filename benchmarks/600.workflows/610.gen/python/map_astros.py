def handler(elem):
    name = elem["name"]
    parts = name.split(" ", 1)
    name = " ".join(reversed(parts))
    elem["name_rev"] = name

    return elem
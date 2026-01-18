def handler(elem):
    full_name:str = elem["name"]
    names = full_name.split(" ")
    names.reverse()
    elem["name_rev"] = " ".join(names)
    return elem
from random import shuffle

def handler(event):
    size = int(event["size"]) if isinstance(event, dict) else len(event)
    elems = list(range(size))
    shuffle(elems)

    data = ""
    for i in elems:
        data += str(i % 255)
        if len(data) > size:
            break

    return data[:size]
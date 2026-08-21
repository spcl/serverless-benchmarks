from random import shuffle

def handler(event):
    size = len(event['len'])
    elems = list(range(size))
    shuffle(elems)

    data = ""
    for i in elems:
        data += str(i % 255)
        if len(data) > size:
            break

    return {'len' : data[:size]}

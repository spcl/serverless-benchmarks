from time import sleep

def handler(event):
    print(event)

    data = (str(i % 255) for i in range(2**4))
    return {"buffer": "".join(data)}
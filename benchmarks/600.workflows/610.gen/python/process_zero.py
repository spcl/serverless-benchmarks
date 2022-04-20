from time import sleep
import requests

def handler(event):
    res = requests.get("http://api.open-notify.org/astros.json")

    data = (str(i % 255) for i in range(2**4))
    return {
        "buffer": "".join(data),
        "astros": res.json()
    }
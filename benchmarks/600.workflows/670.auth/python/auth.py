import random
import string
import pyaes
import base64

KEY = "6368616e676520746869732070617373".encode("utf-8")


def AESModeCTR(plaintext):
    counter = pyaes.Counter(initial_value=0)
    aes = pyaes.AESModeOfOperationCTR(KEY, counter=counter)
    ciphertext = aes.encrypt(plaintext)
    return ciphertext


def AESModeCBC(plaintext):
    # random initialization vector of 16 bytes
    blocks_size = 16
    iv = "InitializationVe"
    pad = 16 - len(plaintext)% blocks_size
    plaintext = str("0" * pad) + plaintext
    aes = pyaes.AESModeOfOperationCBC(KEY, iv=iv)
    ciphertext = aes.encrypt(plaintext)

    return ciphertext.decode("utf-8")


def handler(event):
    message = event["message"]
    token = event["token"]

    res = "unauthorized"
    if token == "allow":
        res = AESModeCTR(message)
        res = base64.b64encode(res).decode("ascii")

    return {
        "response": res
    }
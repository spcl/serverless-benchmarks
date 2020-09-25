#test
config = {
    "block_size": 1024*1024*128
}
result = {}
number = 0
#import
import numpy as np
import time
import uuid
import os
#function
def test_disc(block_size, file_name):
    a = np.ones(int(block_size / 4), dtype=np.dtype("int32")) * 2
    t0 = time.clock()
    np.save(file_name, a)
    t1 = time.clock()
    t2 = time.clock()
    np.load(file_name)
    t3 = time.clock()

    write_time = t1 - t0
    read_time = t3 - t2
    return {"block_size": block_size,
        "write_time": write_time,
        "read_time": read_time}
#run
block_size = config.get("block_size", 100)
file_name = "/tmp/sebs.npy"
result[str(number)] = test_disc(block_size, file_name)
print(result)

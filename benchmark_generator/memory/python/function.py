#test
config = {
    "size_in_bytes": 1024 * 1024
}
result = {}
number = 0
#import
import numpy as np
import time
#function
def allocate(size_in_bytes):
    t0 = time.clock()
    arr = np.ones(int(size_in_bytes/4), dtype=np.dtype("int32"))
    t1 = time.clock()
    return {
        "time": t1 - t0,
        "size_in_bytes": size_in_bytes
    }    
#run
size_of_allocated_memory = config.get("size_in_bytes", 1024 * 1024)     # Default 1 MB
result[str(number)] = (allocate(size_of_allocated_memory))
print(result)

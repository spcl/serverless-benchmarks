#test
config = {
    "iterations": 1000000,
    "operator": "-",
    "type": "float32",
    "array_size": 10000
}
#import
import numpy as np
import time
import operator as op
#function
def workload(number_of_iterations, dtype, array_size, operator):
    a = np.ones(array_size, dtype=dtype) * 2
    b = np.ones(array_size, dtype=dtype) * 3
    t0 = time.clock()
    for i in range(number_of_iterations):
        c = operator(a, b)
    t1 = time.clock()
    return {"number_of_operations": number_of_iterations * array_size,
        "dtype": dtype,
        "time": t1 - t0}
#run
string_to_operator = {
    "+": op.add,
    "-": op.sub,
    "*": op.mul,
    "/": op.truediv,
}
element_type = np.dtype(config.get("type", np.float))
number_of_iterations = config.get("iterations", 10000)
array_size = config.get("array_size", 100)
operator = string_to_operator[config.get("operator", "+")]
result = workload(number_of_iterations, element_type, array_size, operator)
print(result)

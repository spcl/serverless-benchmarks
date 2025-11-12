import datetime

import jax.numpy as jnp
import jax

@jax.jit
def compute(array_1, array_2, a, b, c):
    return jnp.clip(array_1, 2, 10) * a + array_2 * b + c

def initialize(M, N):
    from numpy.random import default_rng
    rng = default_rng(42)
    array_1 = rng.uniform(0, 1000, size=(M, N)).astype(jnp.int64)
    array_2 = rng.uniform(0, 1000, size=(M, N)).astype(jnp.int64)
    a = jnp.int64(4)
    b = jnp.int64(3)
    c = jnp.int64(9)
    return array_1, array_2, a, b, c

def handler(event):

    if "size" in event:
        size = event["size"]
        M = size["M"]
        N = size["N"]
    

    generate_begin = datetime.datetime.now()

    array_1, array_2, a, b, c = initialize(M, N)

    generate_end = datetime.datetime.now()
    
    process_begin = datetime.datetime.now()
    
    results = compute(array_1, array_2, a, b, c)

    process_end = datetime.datetime.now()
    
    # y_re_im = jnp.stack([jnp.real(result), jnp.imag(result)], axis=-1).tolist()

    process_time = (process_end - process_begin) / datetime.timedelta(milliseconds=1)
    generate_time = (generate_end - generate_begin) / datetime.timedelta(milliseconds=1)    

    try:
        results = jax.device_get(results)
    except Exception:
        pass

    if getattr(results, "ndim", 0) == 0 or getattr(results, "size", 0) == 1:
        results = results.item()
    else:
        results = results.tolist()

    return {
            'size': size,
            'result': results,
            'measurement': {
                'compute_time': process_time,
                'generate_time': generate_time
            }
    }

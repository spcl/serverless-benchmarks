import datetime

import jax
import jax.numpy as jnp
from functools import partial


def rng_complex(shape, rng):
    return (rng.random(shape) + rng.random(shape) * 1j)


def initialize(R, K):
    from numpy.random import default_rng
    rng = default_rng(42)

    N = R**K
    X = rng_complex((N, ), rng)
    Y = jnp.zeros_like(X, dtype=jnp.complex128)

    return N, R, K, X, Y

def stockham_fft(N, R, K, x, y):

    # Generate DFT matrix for radix R.
    # Define transient variable for matrix.
    i_coord, j_coord = jnp.mgrid[0:R, 0:R]
    # dft_mat = jnp.empty((R, R), dtype=jnp.complex128)
    dft_mat = jnp.exp(-2.0j * jnp.pi * i_coord * j_coord / R)
    y = x

    ii_coord, jj_coord = jnp.mgrid[0:R, 0:R**K]

    # Main Stockham loop
    for i in range(K):
        # Stride permutation
        yv = jnp.reshape(y, (R**i, R, R**(K - i - 1)))
        tmp_perm = jnp.transpose(yv, axes=(1, 0, 2))

        # Twiddle Factor multiplication
        tmp = jnp.exp(-2.0j * jnp.pi * ii_coord[:, :R**i] * jj_coord[:, :R**i] / R**(i + 1))
        D = jnp.repeat(jnp.reshape(tmp, (R, R**i, 1)), R**(K - i - 1), axis=2)
        tmp_twid = jnp.reshape(tmp_perm, (N, )) * jnp.reshape(D, (N, ))

        # Product with Butterfly
        y = jnp.reshape(dft_mat @ jnp.reshape(tmp_twid, (R, R**(K - 1))),(N, ))

    return y

def handler(event):

    if "size" in event:
        size = event["size"]

    
    generate_begin = datetime.datetime.now()

    N, R, K, X, Y = initialize(2, size)

    generate_end = datetime.datetime.now()
    
    process_begin = datetime.datetime.now()
    
    result = stockham_fft(N, R, K, X, Y)
    
    process_end = datetime.datetime.now()

    y_re_im = jnp.stack([jnp.real(result), jnp.imag(result)], axis=-1).tolist()
    

    process_time = (process_end - process_begin) / datetime.timedelta(milliseconds=1)
    generate_time = (generate_end - generate_begin) / datetime.timedelta(milliseconds=1)    

    return {
            'size': size,
            'result': y_re_im,
            'measurement': {
                'compute_time': process_time,
                'generate_time': generate_time
            }
    }

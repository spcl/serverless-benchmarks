import datetime

import jax.numpy as jnp
import jax
from jax import lax


@jax.jit
def relu(x):
    return jnp.maximum(x, 0)


# Deep learning convolutional operator (stride = 1)
@jax.jit
def conv2d(input, weights):
    K = weights.shape[0]  # Assuming square kernel
    N = input.shape[0]
    H_out = input.shape[1] - K + 1
    W_out = input.shape[2] - K + 1
    C_out = weights.shape[3]
    output = jnp.empty((N, H_out, W_out, C_out), dtype=jnp.float32)

    def row_update(output, i):
        def col_update(output, j):
            input_slice = lax.dynamic_slice(
                input, (0, i, j, 0), (N, K, K, input.shape[-1])
            )
            conv_result = jnp.sum(
                input_slice[:, :, :, :, None] * weights[None, :, :, :], axis=(1, 2, 3)
            )
            output = lax.dynamic_update_slice(
                output, conv_result[:, None, None, :], (0, i, j, 0)
            )
            return output, None

        output, _ = lax.scan(col_update, output, jnp.arange(W_out))
        return output, None

    output, _ = lax.scan(row_update, output, jnp.arange(H_out))
    return output


# Batch normalization operator, as used in ResNet
@jax.jit
def batchnorm2d(x, eps=1e-5):
    mean = jnp.mean(x, axis=0, keepdims=True)
    std = jnp.std(x, axis=0, keepdims=True)
    return (x - mean) / jnp.sqrt(std + eps)


# Bottleneck residual block (after initial convolution, without downsampling)
# in the ResNet-50 CNN (inference)
@jax.jit
def resnet_basicblock(input, conv1, conv2, conv3):
    # Pad output of first convolution for second convolution
    padded = jnp.zeros(
        (input.shape[0], input.shape[1] + 2, input.shape[2] + 2, conv1.shape[3]),
        dtype=jnp.float32,
    )
    padded = lax.dynamic_update_slice(padded, conv2d(input, conv1), (0, 1, 1, 0))
    x = batchnorm2d(padded)
    x = relu(x)

    x = conv2d(x, conv2)
    x = batchnorm2d(x)
    x = relu(x)
    x = conv2d(x, conv3)
    x = batchnorm2d(x)
    return relu(x + input)


def initialize(N, W, H, C1, C2):
    from numpy.random import default_rng

    rng = default_rng(42)

    # Input
    input = rng.random((N, H, W, C1), dtype=jnp.float32)
    # Weights
    conv1 = rng.random((1, 1, C1, C2), dtype=jnp.float32)
    conv2 = rng.random((3, 3, C2, C2), dtype=jnp.float32)
    conv3 = rng.random((1, 1, C2, C1), dtype=jnp.float32)
    return (input, conv1, conv2, conv3)


def handler(event):

    if "size" in event:
        size = event["size"]
        N = size["N"]
        W = size["W"]
        H = size["H"]
        C1 = size["C1"]
        C2 = size["C2"]

    generate_begin = datetime.datetime.now()

    input, conv1, conv2, conv3 = initialize(N, W, H, C1, C2)

    generate_end = datetime.datetime.now()

    process_begin = datetime.datetime.now()

    results = resnet_basicblock(input, conv1, conv2, conv3)

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
        "size": size,
        "result": results,
        "measurement": {"compute_time": process_time, "generate_time": generate_time},
    }

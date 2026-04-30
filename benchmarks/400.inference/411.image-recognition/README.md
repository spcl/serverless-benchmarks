# 411.image-recognition - Image Recognition

**Type:** Inference
**Languages:** Python
**Architecture:** x64

## Description

The benchmark is inspired by MLPerf and implements image recognition with Resnet50. It downloads the input and model from the storage and uses the CPU-only `pytorch` library in Python.

The minimal memory amount is set to 768 MiB due to GCP requirements. It works with 512 MiB on AWS.

## Important Notes

> [!WARNING]
> This benchmark contains PyTorch which is often too large to fit into a code package. Up to Python 3.7, we can directly ship the dependencies. For Python 3.8, we use an additional zipping step that requires additional setup during the first run, making cold invocations slower. Warm invocations are not affected.

> [!WARNING]
> This benchmark does not work on AWS with Python 3.9 and code package due to excessive code size. While it is possible to ship the benchmark by zipping `torchvision` and `numpy` (see `benchmarks/400.inference/411.image-recognition/python/package.sh`), this significantly affects cold startup. On the lowest supported memory configuration of 512 MB, the cold startup can reach 30 seconds, making HTTP trigger unusable due to 30 second timeout of API gateway. Use Docker deployments for these configurations.

> [!WARNING]
> This benchmark does not work on GCP functions gen1 with Python 3.8+ due to excessive code size. Use container deployments on Google Cloud Run for these configurations.


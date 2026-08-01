# 411.image-recognition - Image Recognition

**Type:** Inference
**Languages:** Python, C++
**Architecture:** x64

## Description

The benchmark is inspired by MLPerf and implements image recognition with Resnet50. It downloads the input and model from the storage and uses the CPU-only `pytorch` library in Python.

The minimal memory amount is set to 768 MiB due to GCP requirements. It works with 512 MiB on AWS.

## Important Notes

> [!WARNING]
> This benchmark contains PyTorch which is often too large to fit into a code package. Up to Python 3.7, we can directly ship the dependencies. For Python 3.8, we use an additional zipping step that requires additional setup during the first run, making cold invocations slower. Warm invocations are not affected.

> [!WARNING]
> This benchmark does not fit the AWS Lambda uncompressed code-package limit with any Python version or C++ runtime currently supported by SeBS. SeBS marks AWS package deployment as unsupported for this benchmark. Use `--system-variant container`; retrying the ZIP package cannot succeed.

> [!WARNING]
> This benchmark does not work on GCP functions gen1 with Python 3.8+ due to excessive code size. Use container deployments on Google Cloud Run for these configurations.

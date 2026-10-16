# 421.llm-inference - LLM Inference

**Type:** Inference
**Languages:** Python
**Architecture:** arm64, x64 (AWS container, Python 3.12)

## Description

CPU text generation with vLLM 0.31.0 and `SmolLM2-135M-Instruct`. SeBS automatically prepares the pinned model snapshot and uploads it to its input storage. The function downloads and verifies the model on its first invocation, initializes the engine, and reuses it for warm requests. Inference runs directly through the Python API; no HTTP inference server is involved.

Defaults are 4096 MB memory, a 600-second timeout, float32, a 2048-token context and a 256 MiB KV cache. The `test`, `small` and `large` profiles allow up to 8, 32 and 128 generated tokens respectively, including natural early termination.

## Usage

From an installed SeBS checkout with AWS credentials configured and Docker running:

The included `aws.json` selects an ARM64 container with Python 3.12 in
`eu-central-1` and a 660-second client read timeout to allow cold initialization.

```sh
sebs benchmark invoke 421.llm-inference test \
  --config benchmarks/400.inference/421.llm-inference/aws.json \
  --cache ./cache-llm \
  --trigger library --repetitions 3 --validate \
  --output-dir ./results-llm
```

SeBS builds the function image, compiles vLLM and pushes it to ECR. Weights remain outside the image. No separate model preparation is needed. To use another compatible safetensors snapshot with a chat template, set `SEBS_LLM_MODEL_DIR` to its directory and pass `--update-storage --update-code`. Unset the variable to restore the default model. The default is recorded in `default-model.json`; larger models may exceed the memory budgets.

## Measurements

Application measurements are stored in the SeBS experiment JSON: model download and verification time, engine initialization time, generation time, input/output token counts and model reuse. Times are in microseconds. `tokens_per_second` is **(input tokens + output tokens) / generation seconds**, including prefill and decoding but excluding download and initialization. Warm requests report zero download and initialization time.

## Important Notes

> [!WARNING]
> vLLM is patched to avoid the unused UniProc shared-memory lock for text models, incompatible with the AWS Lambda environment due to restrict access to '/dev/shm', and provide some patches to solve some incompatibilities with Graviton 2 in 'arm' instances. AWS Lambda restricts shared memory, CPU sysfs and NUMA; this configuration targets both ARM64 and x64 architectures.


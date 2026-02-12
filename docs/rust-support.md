# Rust Support for AWS Lambda Benchmarks

This document describes the Rust support implementation for AWS Lambda benchmarks in the SeBS framework.

## Overview

As of November 2025, AWS Lambda officially supports Rust as a Generally Available runtime. This implementation adds full Rust support to the SeBS benchmarking framework for AWS Lambda.

## Requirements

- Rust toolchain (version specified in benchmark configuration)
- AWS Lambda Runtime for Rust (`lambda_runtime` crate)
- Cargo build system

## Architecture

### Runtime Configuration

Rust functions on AWS Lambda use the `provided.al2023` custom runtime. The compiled binary must be named `bootstrap` to be recognized by the Lambda execution environment.

### Build Process

1. Rust code is compiled using Cargo with the appropriate target architecture:
   - `x86_64-unknown-linux-gnu` for x64 architecture
   - `aarch64-unknown-linux-gnu` for ARM64 architecture

2. The compiled binary is renamed to `bootstrap` if necessary

3. The bootstrap binary is packaged in a ZIP file for deployment

## Creating a Rust Benchmark

### 1. Project Structure

Create a Rust directory in your benchmark folder:

```
benchmarks/
  └── YOUR_BENCHMARK/
      └── rust/
          ├── Cargo.toml
          ├── src/
          │   └── main.rs
          └── .gitignore
```

### 2. Cargo.toml Configuration

Your `Cargo.toml` must specify the binary name as `bootstrap`:

```toml
[package]
name = "your-benchmark"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "bootstrap"
path = "src/main.rs"

[dependencies]
lambda_runtime = "0.13"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
tokio = { version = "1", features = ["full"] }
```

### 3. Handler Implementation

Your Rust handler must follow the Lambda Runtime API format:

```rust
use lambda_runtime::{service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Deserialize)]
struct Request {
    // Your input fields
}

#[derive(Serialize)]
struct Response {
    result: YourResultType,
    begin: f64,
    end: f64,
    is_cold: bool,
    request_id: String,
}

static mut IS_COLD: bool = true;

async fn handler(event: LambdaEvent<Request>) -> Result<Response, Error> {
    let (payload, context) = event.into_parts();
    
    let begin = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    
    let is_cold = unsafe {
        let cold = IS_COLD;
        IS_COLD = false;
        cold
    };
    
    // Your benchmark logic here
    
    let end = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    
    Ok(Response {
        result: your_result,
        begin,
        end,
        is_cold,
        request_id: context.request_id,
    })
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    lambda_runtime::run(service_fn(handler)).await
}
```

### 4. Update Benchmark Configuration

Add `"rust"` to the languages array in your benchmark's `config.json`:

```json
{
  "timeout": 120,
  "memory": 128,
  "languages": ["python", "nodejs", "rust"],
  "modules": []
}
```

## Running Rust Benchmarks

Use the standard SeBS command-line interface:

```bash
# Deploy and run a Rust benchmark
./sebs.py benchmark invoke 010.sleep --language rust --language-version 1.80 --deployment aws

# Use container deployment (recommended for consistent builds)
./sebs.py benchmark invoke 010.sleep --language rust --language-version 1.80 --deployment aws --container-deployment
```

## Implementation Details

### Dockerfiles

Two Dockerfiles are provided for Rust:

1. **Dockerfile.build**: Used for building the function code with dependencies
   - Installs Rust toolchain
   - Configures cross-compilation targets
   - Runs the build process

2. **Dockerfile.function**: Used for container-based Lambda deployment
   - Contains the compiled binary
   - Minimal runtime environment

### Build Script

The `rust_installer.sh` script handles:
- Target architecture selection
- Rust target installation
- Cargo build execution
- Binary extraction and naming

### AWS Integration

The AWS deployment module (`sebs/aws/aws.py`) has been updated to:
- Recognize Rust as a language option
- Map Rust to the `provided.al2023` runtime
- Use `bootstrap` as the Lambda handler
- Package Rust binaries correctly

## Example: Sleep Benchmark

A complete example is available at:
`benchmarks/000.microbenchmarks/010.sleep/rust/`

This benchmark demonstrates:
- Basic Lambda Runtime usage
- Cold start detection
- Request/response handling
- Timing measurements

## Performance Considerations

Rust provides several advantages for Lambda functions:

1. **Fast Execution**: Compiled, optimized native code
2. **Low Memory Usage**: No runtime overhead
3. **Fast Cold Starts**: Smaller binary size compared to some runtimes
4. **Predictable Performance**: No garbage collection pauses

## Troubleshooting

### Binary Size Issues

If your binary is too large for direct ZIP upload (>50MB):
- The framework will automatically use S3 upload
- Consider using container deployment for large binaries

### Architecture Mismatch

Ensure you're building for the correct architecture:
- Use `--architecture x64` or `--architecture arm64` flag
- The build system will automatically select the correct Rust target

### Dependencies Not Building

For dependencies with native code:
- Ensure they support Linux targets
- Consider using container deployment for consistent builds

## Additional Resources

- [AWS Lambda Rust Support Announcement](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-lambda-rust/)
- [AWS Lambda Rust Runtime Documentation](https://docs.aws.amazon.com/lambda/latest/dg/lambda-rust.html)
- [Rust Lambda Runtime Crate](https://github.com/awslabs/aws-lambda-rust-runtime)

## Contributing

When adding new Rust benchmarks:

1. Follow the project structure outlined above
2. Include appropriate error handling
3. Document any special dependencies or requirements
4. Test on both x64 and ARM64 architectures if possible
5. Update this documentation if you encounter issues or have suggestions

#!/bin/bash

cd /mnt/function

# Install Rust target for AWS Lambda
if [ "${TARGET_ARCHITECTURE}" == "arm64" ]; then
    RUST_TARGET="aarch64-unknown-linux-gnu"
elif [ "${TARGET_ARCHITECTURE}" == "x64" ]; then
    RUST_TARGET="x86_64-unknown-linux-gnu"
else
    echo "Unsupported architecture: $TARGET_ARCHITECTURE"
    exit 1
fi

# Ensure Cargo.toml exists
if [ ! -f "Cargo.toml" ]; then
    echo "Error: Cargo.toml not found"
    exit 1
fi

# Add the target if not already added
rustup target add ${RUST_TARGET}

# Build the release binary
cargo build --release --target ${RUST_TARGET}

# Copy the binary to the root as 'bootstrap' (required by AWS Lambda custom runtime)
cp target/${RUST_TARGET}/release/bootstrap bootstrap || \
    cp target/${RUST_TARGET}/release/handler bootstrap || \
    (ls target/${RUST_TARGET}/release/ && exit 1)

chmod +x bootstrap

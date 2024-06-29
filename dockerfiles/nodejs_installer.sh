#!/bin/bash

cd /mnt/function

if [ "${TARGET_ARCHITECTURE}" = "arm64" ]; then
    npm install --arch=arm64
elif [ "${TARGET_ARCHITECTURE}" = "x86_64" ]; then
    npm install --arch=x64
else
    echo "Unsupported architecture: $TARGET_ARCHITECTURE"
    exit 1
fi

rm -rf package-lock.json


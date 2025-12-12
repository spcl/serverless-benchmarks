#!/bin/bash

cd /mnt/function

if [ "${TARGET_ARCHITECTURE}" == "arm64" ]; then
        bun install --arch=arm64
elif [ "${TARGET_ARCHITECTURE}" = "x64" ]; then
        bun install --arch=x64
else
        echo "Unsupported architecture: $TARGET_ARCHITECTURE"
        exit 1
fi


bun build --compile --minify --sourcemap runtime.js --outfile bootstrap
rm -r bun.lock node_modules function.js handler.js package.json runtime.js storage.js

#!/bin/bash

cd /mnt/function

if [ "${TARGET_ARCHITECTURE}" == "arm64" ]; then
        bun install --arch=arm64
        COMPILE_TARGET=bun-linux-arm64
elif [ "${TARGET_ARCHITECTURE}" = "x64" ]; then
        bun install --arch=x64
        COMPILE_TARGET=bun-linux-x64
else
        echo "Unsupported architecture: $TARGET_ARCHITECTURE"
        exit 1
fi


bun build --compile --minify --target $COMPILE_TARGET --sourcemap runtime.js --outfile bootstrap
# For AWS we need to compile the bun/js files into a bootstrap binary
rm -r bun.lock node_modules function.js handler.js package.json runtime.js storage.js

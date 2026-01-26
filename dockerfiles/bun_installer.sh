#!/bin/bash

cd /mnt/function

if [ "${TARGET_ARCHITECTURE}" == "arm64" ]; then
        bun install --arch=arm64
        BUN_ARCH_URL="https://github.com/oven-sh/bun/releases/latest/download/bun-linux-aarch64.zip"
elif [ "${TARGET_ARCHITECTURE}" = "x64" ]; then
        bun install --arch=x64 --platform=linux
        BUN_ARCH_URL="https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip"
else
        echo "Unsupported architecture: $TARGET_ARCHITECTURE"
        exit 1
fi

# install bun directly
curl -L -o bun.zip $BUN_ARCH_URL
unzip -j bun.zip */bun
chmod +x bun
rm bun.zip

rm -r bun.lock
# moves to correct directory on AWS if needed
echo -e '#!/bin/bash\nif $LAMBDA_TASK_ROOT; then cd $LAMBDA_TASK_ROOT; fi\n./bun --bun runtime.js' > bootstrap
chmod +x bootstrap

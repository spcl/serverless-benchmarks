#!/bin/bash
set -e
if [ -f /nvm/nvm.sh ]; then
  . /nvm/nvm.sh
fi
#
cd /mnt/function

if [ "${TARGET_ARCHITECTURE}" == "arm64" ]; then
        npm install --arch=arm64 --cpu=arm64 --os=linux --libc=glibc
elif [ "${TARGET_ARCHITECTURE}" = "x64" ]; then
        npm install --arch=x64 --cpu=x64 --os=linux --libc=glibc
else
        echo "Unsupported architecture: $TARGET_ARCHITECTURE"
        exit 1
fi

rm -rf package-lock.json

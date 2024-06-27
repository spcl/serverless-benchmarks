#!/bin/bash

if [ -f $FILE ]; then
  . /nvm/nvm.sh
fi
cd /mnt/function && npm install --target_arch=${TARGET_ARCHITECTURE} && rm -rf package-lock.json


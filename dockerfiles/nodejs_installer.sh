#!/bin/bash

cd /mnt/function && npm install --target_arch=${TARGET_ARCHITECTURE} && rm -rf package-lock.json


#!/bin/bash
set -e
if [ -f /nvm/nvm.sh ]; then
  . /nvm/nvm.sh
fi
#
cd /mnt/function

case "${TARGET_ARCHITECTURE}" in
  arm64|x64) ;;
  *)
    echo "Unsupported architecture: $TARGET_ARCHITECTURE"
    exit 1
    ;;
esac

# package-lock.json is the benchmark's lockfile for this deployment:
# npm ci installs exactly the locked versions and verifies their integrity hashes.
# Optional platform-specific packages, e.g., prebuilt binaries of sharp,
# are selected for the target architecture through --cpu, --os, and --libc;
# SeBS architecture names are the ones of npm.
npm ci --omit=dev --cpu="${TARGET_ARCHITECTURE}" --os=linux --libc=glibc

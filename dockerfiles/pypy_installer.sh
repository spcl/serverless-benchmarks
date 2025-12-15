#!/bin/bash
set -euo pipefail

cd /mnt/function

# Download and unpack PyPy
curl -L -o pypy.tar.bz2 https://downloads.python.org/pypy/pypy3.11-v7.3.20-linux64.tar.bz2
tar -xjf pypy.tar.bz2
mv pypy3.11-v7.3.20-linux64 pypy
rm pypy.tar.bz2
chmod -R +x pypy/bin
export PATH=/mnt/function/pypy/bin:$PATH

# Ensure pip is available
python -m ensurepip
python -mpip install -U pip wheel

# Where to place dependencies for Azure/AWS
REQ_TARGET=".python_packages/lib/site-packages"
mkdir -p "${REQ_TARGET}"

# Platform pin for arm64 if needed
# WARNING: Removing the conditional might break PyPy builds or install CPython-only libs.
PLATFORM_ARG=""
if [[ "${TARGET_ARCHITECTURE:-}" == "arm64" ]]; then
  PLATFORM_ARG="--platform manylinux_2_17_aarch64 --only-binary=:all:"
fi

# Pick the best matching requirements file
if [[ "${TARGET_ARCHITECTURE:-}" == "arm64" && -f "requirements.txt.arm.${PYTHON_VERSION}" ]]; then
  REQ_FILE="requirements.txt.arm.${PYTHON_VERSION}"
elif [[ -f "requirements.txt.${PYTHON_VERSION}" ]]; then
  REQ_FILE="requirements.txt.${PYTHON_VERSION}"
else
  REQ_FILE="requirements.txt"
fi

# Install benchmark deps into the target directory
python -mpip install ${PLATFORM_ARG} -r "${REQ_FILE}" -t "${REQ_TARGET}"

# Run optional benchmark packaging hook
if [[ -f "${SCRIPT_FILE:-}" ]]; then
  /bin/bash "${SCRIPT_FILE}" "${REQ_TARGET}"
fi
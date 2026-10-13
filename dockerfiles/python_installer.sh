#!/bin/bash
set -e
cd /mnt/function

PLATFORM_ARG=""
if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]]; then
  PLATFORM_ARG="--platform manylinux_2_17_aarch64 --only-binary=:all:"
elif [[ "${TARGET_ARCHITECTURE}" == "x64" ]] && [[ "$(uname -m)" != "x86_64" ]]; then
  # A multi-platform build image runs natively on ARM machines (e.g., Apple Silicon):
  # download x86 wheels instead of the build container's own.
  PLATFORM_ARG="--platform manylinux_2_17_x86_64 --only-binary=:all:"
fi

if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]] && [[ -f "requirements.txt.arm.${PYTHON_VERSION}" ]]; then

  pip3 install ${PLATFORM_ARG} -r requirements.txt.arm.${PYTHON_VERSION} -t .python_packages/lib/site-packages

elif [[ -f "requirements.txt.${PYTHON_VERSION}" ]]; then

  pip3 install ${PLATFORM_ARG} -r requirements.txt.${PYTHON_VERSION} -t .python_packages/lib/site-packages

else

  pip3 install ${PLATFORM_ARG} -r requirements.txt -t .python_packages/lib/site-packages

fi

if [[ -f "${SCRIPT_FILE}" ]]; then
  /bin/bash ${SCRIPT_FILE} .python_packages/lib/site-packages
fi

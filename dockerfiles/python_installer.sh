#!/bin/bash
set -e
cd /mnt/function

if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]]; then
  TARGET_MACHINE="aarch64"
else
  TARGET_MACHINE="x86_64"
fi

# Install only wheels: no package is compiled, so packages never depend on the build machine.
PLATFORM_ARG="--only-binary=:all:"
if [[ "$(uname -m)" != "${TARGET_MACHINE}" ]]; then
  # Cross-architecture build, e.g., arm64 functions on an x86 machine, or x64 functions
  # on Apple Silicon, where the multi-platform build image runs natively.
  # Without --platform, pip would install wheels for the build container's architecture.
  # pip does not expand --platform to compatible tags, so we list all manylinux tags up to
  # the image's glibc: both variants of a build image use the same distribution and glibc.
  GLIBC_MINOR=$(python3 -c "import platform; print(platform.libc_ver()[1].split('.')[1])")
  LOWEST_MINOR=5
  LEGACY_TAGS="manylinux2014 manylinux2010 manylinux1"
  if [[ "${TARGET_MACHINE}" == "aarch64" ]]; then
    LOWEST_MINOR=17
    LEGACY_TAGS="manylinux2014"
  fi
  for ((minor = GLIBC_MINOR; minor >= LOWEST_MINOR; minor--)); do
    PLATFORM_ARG="${PLATFORM_ARG} --platform manylinux_2_${minor}_${TARGET_MACHINE}"
  done
  for tag in ${LEGACY_TAGS}; do
    PLATFORM_ARG="${PLATFORM_ARG} --platform ${tag}_${TARGET_MACHINE}"
  done
  # Plain Linux wheels, e.g., the PyTorch CPU wheels pinned by 411.image-recognition.
  PLATFORM_ARG="${PLATFORM_ARG} --platform linux_${TARGET_MACHINE}"
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

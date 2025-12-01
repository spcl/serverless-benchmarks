#!/bin/bash

cd /mnt/function

#TODO: If the base image OS is not centOS based, change to apt
yum install -y tar bzip2 gzip

#TODO: make version configurable
curl -L -o pypy.tar.bz2 https://downloads.python.org/pypy/pypy3.11-v7.3.20-linux64.tar.bz2
tar -xjf pypy.tar.bz2 
mv pypy3.11-v7.3.20-linux64 /opt/pypy 
rm pypy.tar.bz2
chmod -R +x /opt/pypy/bin
export PATH=/opt/pypy/bin:$PATH
python -m ensurepip
python -mpip install -U pip wheel

#Probably remove this conditional, might break pypy builds, might lead to installation of CPython libraries
PLATFORM_ARG=""
if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]]; then
  PLATFORM_ARG="--platform manylinux_2_17_aarch64 --only-binary=:all:"
fi

if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]] && [[ -f "requirements.txt.arm.${PYTHON_VERSION}" ]]; then

  pip3 -q install ${PLATFORM_ARG} -r requirements.txt.arm.${PYTHON_VERSION} -t .python_packages/lib/site-packages

elif [[ -f "requirements.txt.${PYTHON_VERSION}" ]]; then

  pip3 -q install ${PLATFORM_ARG} -r requirements.txt.${PYTHON_VERSION} -t .python_packages/lib/site-packages

else

  pip3 -q install ${PLATFORM_ARG} -r requirements.txt -t .python_packages/lib/site-packages

fi

if [[ -f "${SCRIPT_FILE}" ]]; then
  /bin/bash ${SCRIPT_FILE} .python_packages/lib/site-packages
fi



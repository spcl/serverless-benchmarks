#!/bin/bash

env_dir=sebs-virtualenv
if [ ! -d ${env_dir} ]; then
  mkdir ${env_dir}
  python3 -mvenv ${env_dir}
  source ${env_dir}/bin/activate
  echo 'Install docker package for python'
  pip3 install docker wheel bottle waitress minio nodeenv requests py-cpuinfo
  # aws
  pip3 install boto3
  # azure
  pip3 install azure-storage-blob
fi

## node
#env_dir=sebs-nodeenv
#if [ ! -d ${env_dir} ]; then
#  nodeenv ${env_dir}
#  source ${env_dir}/bin/activate
#fi
#
git submodule update --init --recursive
#
#build_dir=sebs-build
#mkdir -p ${build_dir}
#mkdir -p ${build_dir}/install
#install_dir=$(pwd)/${build_dir}/install

pushd third-party/pypapi > /dev/null && git checkout low_api_overflow
pip3 install -r requirements.txt
python3 setup.py build && python3 pypapi/papi_build.py
popd > /dev/null

#mkdir -p ${install_dir}/pypapi
#cd third-party/pypapi
#cp -R pypapi/*.py ${install_dir}/pypapi
#cp -R pypapi/*.so ${install_dir}/pypapi
#cd ..


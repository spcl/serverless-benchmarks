
env_dir=sebs-virtualenv
if [ ! -d ${env_dir} ]; then
  mkdir ${env_dir}
  python3 -mvenv ${env_dir}
  source ${env_dir}/bin/activate
  echo 'Install docker package for python'
  pip3 install docker wheel
fi

git submodule update --init --recursive

build_dir=sebs-build
mkdir -p ${build_dir}
mkdir -p ${build_dir}/install
install_dir=$(pwd)/${build_dir}/install
if [ ! -d ${build_dir} ]; then

  cd third-party/pypapi && git checkout low_api_overflow
  pip3 install -r requirements.txt
  python3 setup.py build && python3 pypapi/papi_build.py
  cd ..

fi
mkdir -p ${install_dir}/pypapi
cd third-party/pypapi
cp -R pypapi/*.py ${install_dir}/pypapi
cp -R pypapi/*.so ${install_dir}/pypapi
cd ..



env_dir=sebs-virtualenv
mkdir ${env_dir}
python3 -mvenv ${env_dir}
source ${env_dir}/bin/activate

echo 'Install docker package for python'
pip3 install docker

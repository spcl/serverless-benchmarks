#!/usr/bin/env python3

import argparse
import os
import subprocess

from tools.fission_preparation import check_if_minikube_installed, check_if_k8s_installed, check_if_helm_installed, \
    check_if_fission_cli_installed, install_fission_cli

parser = argparse.ArgumentParser(description="Install SeBS and dependencies.")
parser.add_argument("--with-pypapi", action="store_true")
parser.add_argument("--with-fission", action="store_true")
args = parser.parse_args()


def execute(cmd):
    ret = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True
    )
    if ret.returncode:
        raise RuntimeError(
            "Running {} failed!\n Output: {}".format(cmd, ret.stdout.decode("utf-8"))
        )
    return ret.stdout.decode("utf-8")

# env_dir="sebs-virtualenv"
#
# print("Creating Python virtualenv at {}".format(env_dir))
# execute("python3 -mvenv {}".format(env_dir))
#
# print("Install Python dependencies with pip")
# execute(". {}/bin/activate && pip3 install -r requirements.txt".format(env_dir))
#
# print("Configure mypy extensions")
# execute(". {}/bin/activate && mypy_boto3".format(env_dir))
#
# print("Initialize git submodules")
# execute("git submodule update --init --recursive")


if args.with_pypapi:
    print("Build and install pypapi")
    cur_dir = os.getcwd()
    os.chdir(os.path.join("third-party", "pypapi"))
    execute("git checkout low_api_overflow")
    execute("pip3 install -r requirements.txt")
    execute("python3 setup.py build")
    execute("python3 pypapi/papi_build.py")
    os.chdir(cur_dir)

if args.with_fission:
    check_if_minikube_installed()
    check_if_k8s_installed()
    check_if_helm_installed()
    try:
        check_if_fission_cli_installed(throws_error=True)
    except subprocess.CalledProcessError:
        install_fission_cli()
        check_if_fission_cli_installed()

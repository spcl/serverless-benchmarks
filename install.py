#!/usr/bin/env python3

import argparse
import os
import subprocess

parser = argparse.ArgumentParser(description="Install SeBS and dependencies.")
parser.add_argument('--venv', metavar='DIR', type=str, default="python-venv", help='destination of local Python virtual environment')
parser.add_argument('--python-path', metavar='DIR', type=str, default="python3", help='Path to local Python installation.')
for deployment in ["aws", "azure", "gcp", "local"]:
    parser.add_argument(f"--{deployment}", action="store_const", const=True, default=True, dest=deployment)
    parser.add_argument(f"--no-{deployment}", action="store_const", const=False, dest=deployment)
parser.add_argument("--with-pypapi", action="store_true")
parser.add_argument("--force-rebuild-docker-images", default=False, action="store_true")
parser.add_argument("--dont-rebuild-docker-images", default=False, action="store_true")
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

env_dir=args.venv

if not os.path.exists(env_dir):
    print("Creating Python virtualenv at {}".format(env_dir))
    execute(f"{args.python_path} -mvenv {env_dir}")
    execute(". {}/bin/activate && pip install --upgrade pip".format(env_dir))
else:
    print("Using existing Python virtualenv at {}".format(env_dir))

print("Install Python dependencies with pip")
execute(". {}/bin/activate && pip3 install -r requirements.txt --upgrade".format(env_dir))

if args.aws:
    print("Install Python dependencies for AWS")
    execute(". {}/bin/activate && pip3 install -r requirements.aws.txt".format(env_dir))
    if args.force_rebuild_docker_images or (os.getuid() != 1000 and not args.dont_rebuild_docker_images):
        print(f"AWS: rebuild Docker images for current user ID: {os.getuid()}")
        execute(". {}/bin/activate && tools/build_docker_images.py --deployment aws".format(env_dir))
    elif os.getuid() != 1000 and args.dont_rebuild_docker_images:
        print(f"AWS: Docker images are built for user with UID 1000, current UID: {os.getuid()}."
                "Skipping rebuild as requested by user, but recommending to rebuild the images")

if args.azure:
    print("Install Python dependencies for Azure")
    execute(". {}/bin/activate && pip3 install -r requirements.azure.txt".format(env_dir))
    if args.force_rebuild_docker_images or (os.getuid() != 1000 and not args.dont_rebuild_docker_images):
        print(f"Azure: rebuild Docker images for current user ID: {os.getuid()}")
        execute(". {}/bin/activate && tools/build_docker_images.py --deployment azure".format(env_dir))
    elif os.getuid() != 1000 and args.dont_rebuild_docker_images:
        print(f"Azure: Docker images are built for user with UID 1000, current UID: {os.getuid()}."
                "Skipping rebuild as requested by user, but recommending to rebuild the images")

if args.gcp:
    print("Install Python dependencies for GCP")
    execute(". {}/bin/activate && pip3 install -r requirements.gcp.txt".format(env_dir))
    if args.force_rebuild_docker_images or (os.getuid() != 1000 and not args.dont_rebuild_docker_images):
        print(f"GCP: rebuild Docker images for current user ID: {os.getuid()}")
        execute(". {}/bin/activate && tools/build_docker_images.py --deployment gcp".format(env_dir))
    elif os.getuid() != 1000 and args.dont_rebuild_docker_images:
        print(f"GCP: Docker images are built for user with UID 1000, current UID: {os.getuid()}."
                "Skipping rebuild as requested by user, but recommending to rebuild the images")

if args.local:
    print("Install Python dependencies for local")
    execute(". {}/bin/activate && pip3 install -r requirements.local.txt".format(env_dir))
    if not args.dont_rebuild_docker_images:
        print("Initialize Docker image for local storage.")
        execute("docker pull minio/minio:latest")

print("Initialize git submodules")
execute("git submodule update --init --recursive")

if args.with_pypapi:
    print("Build and install pypapi")
    cur_dir = os.getcwd()
    os.chdir(os.path.join("third-party", "pypapi"))
    execute("git checkout low_api_overflow")
    execute("pip3 install -r requirements.txt")
    execute("python3 setup.py build")
    execute("python3 pypapi/papi_build.py")
    os.chdir(cur_dir)


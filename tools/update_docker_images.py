#!/usr/bin/env python3

import argparse
import docker
import json
import os
from typing import Optional

PROJECT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.path.pardir)
DOCKER_DIR = os.path.join(PROJECT_DIR, "dockerfiles")

parser = argparse.ArgumentParser(description="Run local app experiments.")
parser.add_argument(
    "--deployment", default=None, choices=["local", "aws", "azure", "gcp", "openwhisk"], action="store"
)
parser.add_argument("--type", default=None, choices=["build", "run", "manage", "function"], action="store")
parser.add_argument("--language", default=None, choices=["python", "nodejs"], action="store")
parser.add_argument("--language-version", default=None, type=str, action="store")
args = parser.parse_args()
config = json.load(open(os.path.join(PROJECT_DIR, "config", "systems.json"), "r"))
repository = config["general"]["docker_repository"]
client = docker.from_env()

def pull(image_name):

    image_name = f'{repository}:{image_name}'
    previous_sha: Optional[str]
    try:
        img = client.images.get(image_name)
        previous_sha = img.attrs['Id']
    except docker.errors.ImageNotFound:
        previous_sha = None
        print(f"Ignoring not present image: {image_name}")
        return

    img = client.images.pull(image_name)

    if img.attrs['Id'] != previous_sha:
        print(f"Updated image: {image_name}")
    else:
        print(f"Image up-to-date: {image_name}")

def generic_pull(image_type, system, language=None, version=None):

    if language is not None and version is not None:
        image_name = f"{image_type}.{system}.{language}.{version}"
    else:
        image_name = f"{image_type}.{system}"

    pull(image_name)

benchmarks = {
    "python": [
        "110.dynamic-html",
        "120.uploader",
        "210.thumbnailer",
        "220.video-processing",
        "311.compression",
        "411.image-recognition",
        "501.graph-pagerank",
        "502.graph-mst",
        "503.graph-bfs",
        "504.dna-visualisation",
    ],
    "nodejs": [
        "110.dynamic-html",
        "120.uploader",
        "210.thumbnailer"
    ]
}

def pull_function(image_type, system, language, language_version):

    for bench in benchmarks[language]:
        image_name = f"{image_type}.{system}.{bench}.{language}-{language_version}"
        pull(image_name)

def pull_language(system, language, language_config):
    configs = []
    if "base_images" in language_config:
        for version, base_image in language_config["base_images"].items():
            if args.language_version is not None and args.language_version == version:
                configs.append([version, base_image])
            elif args.language_version is None:
                configs.append([version, base_image])
    else:
        configs.append([None, None])

    for image in configs:
        if args.type is None:
            for image_type in language_config["images"]:

                if image_type == "function":
                    pull_function(image_type, system, language, image[0])
                else:
                    generic_pull(image_type, system, language, image[0])
        else:
            generic_pull(args.type, system, language, image[0])


def pull_systems(system, system_config):

    if args.type == "manage":
        if "images" in system_config:
            generic_pull(args.type, system)
        else:
            print(f"Skipping manage image for {system}")
    else:
        if args.language:
            pull_language(system, args.language, system_config["languages"][args.language])
        else:
            for language, language_dict in system_config["languages"].items():
                pull_language(system, language, language_dict)
            # Build additional types
            if "images" in system_config:
                for image_type, image_config in system_config["images"].items():
                    generic_pull(image_type, system)


if args.deployment is None:
    for system, system_dict in config.items():
        if system == "general":
            continue
        pull_systems(system, system_dict)
else:
    pull_systems(args.deployment, config[args.deployment])

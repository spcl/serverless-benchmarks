#!/usr/bin/env python3
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Archive a static ffmpeg build as a SeBS image for the 220.video-processing benchmark.

The benchmark uses a static, glibc-based ffmpeg from BtbN/FFmpeg-Builds. Upstream only
keeps its builds for a limited time, so we archive them as a multi-arch image,
spcleth/serverless-benchmarks:ffmpeg-reproducibility-archive-<version>, similar to the
Minio archive.

The binaries come from one of two sources:

* download (default): the pinned BtbN release tarballs, verified against their sha256.
* build: BtbN's build scripts at a pinned commit, for when the release has been
  deleted upstream. This takes several hours per architecture. BtbN can only build
  a git tag or branch, so this builds the FFmpeg release tag, not the exact snapshot
  of the downloaded build. It is pushed under a separate <tag>-rebuild tag.

Building needs a buildx builder that supports multi-platform images, e.g.,
`docker buildx create --use`; pushing also needs `docker login` with access to the
repository. After pushing, copy the printed FFMPEG_IMAGE line into
benchmarks/200.multimedia/220.video-processing/init.sh.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPOSITORY = "spcleth/serverless-benchmarks"
TAG_PREFIX = "ffmpeg-reproducibility-archive"
# The build context contains dist/<arch>/{ffmpeg,LICENSE.txt,SOURCE}.
DOCKERFILE = """FROM scratch
ARG TARGETARCH
COPY dist/${TARGETARCH}/ /
"""
BTBN_REPO = "https://github.com/BtbN/FFmpeg-Builds"

# Docker architecture -> BtbN target.
TARGETS = {"amd64": "linux64", "arm64": "linuxarm64"}

RELEASES = {
    "9.0.2": {
        # Month-end autobuilds are retained upstream for two years.
        "btbn_release": "autobuild-2026-10-31-12-59",
        "build_name": "ffmpeg-n9.0.2-39-g7adfbe40dc",
        "sha256": {
            "amd64": "73e29a56974ae5a651133a04584c7483b21afe941e17dc91d79814a758b608d3",
            "arm64": "6cad88ae5bcec356cfc5d7979a036cc4007128201928a0cf243df3db483276cc",
        },
        # Used only for --source build: the commit of btbn_release, and the FFmpeg tag
        # to build (the downloaded build is 39 commits ahead of it on release/9.0).
        "btbn_commit": "5031c6f1082414e53688d39e521849905071070d",
        "ffmpeg_ref": "n9.0.2",
        "addin": "9.0",
    },
}


def run(cmd: list, **kwargs) -> None:
    """Run a command, echoing it first, and fail on a non-zero exit code."""
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def sha256sum(path: Path) -> str:
    """Compute the sha256 digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(release: dict, arch: str, work: Path) -> tuple:
    """Download and verify the BtbN release tarball; return its path and source note."""
    name = f"{release['build_name']}-{TARGETS[arch]}-gpl-{release['addin']}.tar.xz"
    url = f"{BTBN_REPO}/releases/download/{release['btbn_release']}/{name}"
    tarball = work / name
    print(f"Downloading {url}", flush=True)
    with urllib.request.urlopen(url) as response, open(tarball, "wb") as f:
        shutil.copyfileobj(response, f)

    actual = sha256sum(tarball)
    if actual != release["sha256"][arch]:
        raise RuntimeError(
            f"Checksum mismatch for {name}: expected {release['sha256'][arch]}, got {actual}"
        )
    return tarball, f"{BTBN_REPO}/releases/tag/{release['btbn_release']} {name}"


def build(release: dict, arch: str, work: Path) -> tuple:
    """Rebuild with BtbN's scripts at the pinned commit; return the tarball and source note."""
    repo = work / f"btbn-{arch}"
    run(["git", "clone", "--quiet", BTBN_REPO, repo])
    run(["git", "-C", repo, "checkout", "--quiet", release["btbn_commit"]])

    target = TARGETS[arch]
    env = dict(os.environ, GIT_BRANCH_OVERRIDE=release["ffmpeg_ref"])
    run(["./makeimage.sh", target, "gpl", release["addin"]], cwd=repo, env=env)
    run(["./build.sh", target, "gpl", release["addin"]], cwd=repo, env=env)

    tarballs = list((repo / "artifacts").glob("*.tar.xz"))
    if len(tarballs) != 1:
        raise RuntimeError(f"Expected one build artifact, found {tarballs}")
    note = f"{BTBN_REPO}/commit/{release['btbn_commit']} built from FFmpeg {release['ffmpeg_ref']}"
    return tarballs[0], note


def extract(tarball: Path, source_note: str, dest: Path) -> None:
    """Place ffmpeg, its license, and a note on its source into dest."""
    dest.mkdir(parents=True)
    with tarfile.open(tarball) as tar:
        for member in tar.getmembers():
            # Layout: <build name>/bin/ffmpeg and <build name>/LICENSE.txt
            parts = Path(member.name).parts[1:]
            if parts in (("bin", "ffmpeg"), ("LICENSE.txt",)):
                member.name = parts[-1]
                tar.extract(member, dest, filter="data")

    if not (dest / "ffmpeg").is_file() or not (dest / "LICENSE.txt").is_file():
        raise RuntimeError(f"{tarball} does not contain bin/ffmpeg and LICENSE.txt")
    (dest / "ffmpeg").chmod(0o755)
    (dest / "SOURCE").write_text(
        f"FFmpeg source: https://github.com/FFmpeg/FFmpeg\n{source_note}\n"
    )


def main() -> int:
    """Fetch or build the binaries for all architectures and build the archive image."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("version", nargs="?", default="9.0.2", choices=sorted(RELEASES))
    parser.add_argument("--source", choices=["download", "build"], default="download")
    parser.add_argument(
        "--push", action="store_true", help="push the image; otherwise only build it"
    )
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()

    release = RELEASES[args.version]
    image = f"{REPOSITORY}:{TAG_PREFIX}-{args.version}"
    if args.source == "build":
        image += "-rebuild"
    fetch = download if args.source == "download" else build

    work = Path(tempfile.mkdtemp(prefix="sebs-ffmpeg-"))
    try:
        for arch in TARGETS:
            tarball, note = fetch(release, arch, work)
            extract(tarball, note, work / "context" / "dist" / arch)

        metadata = work / "metadata.json"
        cmd = [
            "docker",
            "buildx",
            "build",
            "--platform",
            ",".join(f"linux/{arch}" for arch in TARGETS),
            "--provenance=false",
            "--file",
            "-",
            "--tag",
            image,
            "--metadata-file",
            metadata,
        ]
        if args.push:
            cmd.append("--push")
        run(cmd + [work / "context"], input=DOCKERFILE.encode())

        if args.push:
            digest = json.loads(metadata.read_text())["containerimage.digest"]
            print(f'\nFFMPEG_IMAGE="{image}@{digest}"')
        else:
            print(f"\nBuilt {image} without pushing; rerun with --push to publish it.")
    finally:
        if args.keep:
            print(f"Working directory: {work}")
        else:
            shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())

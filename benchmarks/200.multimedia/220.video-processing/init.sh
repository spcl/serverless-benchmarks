#!/bin/bash
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

DIR=$1
VERBOSE=$2
TARGET_ARCHITECTURE=$3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

set -euo pipefail

# Static glibc-based ffmpeg build (https://github.com/BtbN/FFmpeg-Builds), archived
# by tools/ffmpeg_archive.py and pinned by digest of the multi-arch index
# so that every deployment gets the exact same binary.
# TODO: append "@sha256:<digest>" printed by tools/ffmpeg_archive.py --push.
FFMPEG_IMAGE="spcleth/serverless-benchmarks:ffmpeg-reproducibility-archive-9.0.2"

# SeBS calls the x86_64 architecture "x64", Docker calls it "amd64".
DOCKER_ARCH="${TARGET_ARCHITECTURE}"
if [[ "${DOCKER_ARCH}" == "x64" ]]; then
    DOCKER_ARCH="amd64"
fi

docker build --quiet --platform "linux/${DOCKER_ARCH}" \
    --output "type=local,dest=${DIR}/ffmpeg" - <<EOF
FROM scratch
COPY --from=${FFMPEG_IMAGE} / /
EOF

# Sanity check - avoid issues where extraction silently fails.
if [ ! -x "${DIR}/ffmpeg/ffmpeg" ]; then
    echo "ERROR: ffmpeg binary missing after packaging" >&2
    exit 1
fi

# copy watermark
cp -r "${SCRIPT_DIR}/resources" "${DIR}"

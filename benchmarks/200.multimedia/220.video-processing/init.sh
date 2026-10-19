#!/bin/bash
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

DIR=$1
VERBOSE=$2
TARGET_ARCHITECTURE=$3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

set -euo pipefail

# Static ffmpeg build (https://github.com/wader/static-ffmpeg), pinned by digest
# of the multi-arch index so that every deployment gets the exact same binary.
FFMPEG_IMAGE="mwader/static-ffmpeg:9.0.2@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b"

# SeBS calls the x86_64 architecture "x64", Docker calls it "amd64".
DOCKER_ARCH="${TARGET_ARCHITECTURE}"
if [[ "${DOCKER_ARCH}" == "x64" ]]; then
    DOCKER_ARCH="amd64"
fi

docker build --quiet --platform "linux/${DOCKER_ARCH}" \
    --output "type=local,dest=${DIR}/ffmpeg" - <<EOF
FROM scratch
COPY --from=${FFMPEG_IMAGE} /ffmpeg /ffmpeg
EOF

# Sanity check - avoid issues where extraction silently fails.
if [ ! -x "${DIR}/ffmpeg/ffmpeg" ]; then
    echo "ERROR: ffmpeg binary missing after packaging" >&2
    exit 1
fi

# copy watermark
cp -r "${SCRIPT_DIR}/resources" "${DIR}"

#!/bin/bash
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

DIR=$1
VERBOSE=$2
TARGET_ARCHITECTURE=$3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

set -euo pipefail

# This currently points to 7.0.2 - will likely change in the future, but we do not have
# a persistent link.
if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]]; then
    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
else
    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
fi

if command -v wget &>/dev/null; then
    wget "${FFMPEG_URL}" -P "${DIR}"
elif command -v curl &>/dev/null; then
    curl -fsL "${FFMPEG_URL}" -o "${DIR}/$(basename ${FFMPEG_URL})"
else
    echo "ERROR: neither wget nor curl available" >&2
    exit 1
fi

pushd "${DIR}" >/dev/null
tar -xf ffmpeg-release-*-static.tar.xz
rm *.tar.xz
mv ffmpeg-* ffmpeg
rm -f ffmpeg/ffprobe 
# make the binary executable
chmod 755 ffmpeg/ffmpeg
popd >/dev/null

# Fail loudly if the binary isn't actually there.
# Sanity check - avoid issues where download silently fails.
if [ ! -x "${DIR}/ffmpeg/ffmpeg" ]; then
    echo "ERROR: ffmpeg binary missing after packaging" >&2
    exit 1
fi

# copy watermark
cp -r "${SCRIPT_DIR}/resources" "${DIR}"

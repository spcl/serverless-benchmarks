# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
#!/bin/bash

DIR=$1
VERBOSE=$2
TARGET_ARCHITECTURE=$3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

if [[ "${TARGET_ARCHITECTURE}" == "arm64" ]]; then
    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
else
    FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
fi

if command -v wget &>/dev/null; then
    wget -q "${FFMPEG_URL}" -P "${DIR}"
else
    curl -sL "${FFMPEG_URL}" -o "${DIR}/$(basename ${FFMPEG_URL})"
fi

pushd "${DIR}" >/dev/null
tar -xf ffmpeg-release-*-static.tar.xz
rm *.tar.xz
mv ffmpeg-* ffmpeg
rm -f ffmpeg/ffprobe 
# make the binary executable
chmod 755 ffmpeg/ffmpeg
popd >/dev/null

# copy watermark
cp -r "${SCRIPT_DIR}/resources" "${DIR}"

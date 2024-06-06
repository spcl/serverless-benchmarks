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

wget -q ${FFMPEG_URL} -P ${DIR}

pushd ${DIR} >/dev/null
tar -xf ffmpeg-release-*-static.tar.xz
rm *.tar.xz
mv ffmpeg-* ffmpeg
rm -f ffmpeg/ffprobe 
# make the binary executable
chmod 755 ffmpeg/ffmpeg
popd >/dev/null

# copy watermark
cp -r ${SCRIPT_DIR}/resources ${DIR}

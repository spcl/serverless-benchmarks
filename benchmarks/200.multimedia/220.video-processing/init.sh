#!/bin/bash

DIR=$1
VERBOSE=$2
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -P ${DIR}
pushd ${DIR} >/dev/null
tar -xf ffmpeg-release-amd64-static.tar.xz
rm *.tar.xz
mv ffmpeg-* ffmpeg
rm ffmpeg/ffprobe
# make the binary executable
chmod 755 ffmpeg/ffmpeg
popd >/dev/null

# copy watermark
cp -r ${SCRIPT_DIR}/resources ${DIR}

# 220.video-processing - Video Processing

**Type:** Multimedia
**Languages:** Python
**Architecture:** x64, arm64

## Description

The benchmark implements two operations on video files: adding a watermark and creating a gif. Both input and output media are passed through the cloud storage. To process the video, the benchmark uses `ffmpeg`. The benchmark ships a static `ffmpeg` binary extracted from the [`mwader/static-ffmpeg`](https://github.com/wader/static-ffmpeg) Docker image, pinned by digest in `init.sh`.

While 512 MB is technically sufficient and works well for the watermark operations, the `large` input converts the video into a gif which is more computationally intensive. On AWS, you should expect around ~30 seconds runtime on 1024 MiB allocation.

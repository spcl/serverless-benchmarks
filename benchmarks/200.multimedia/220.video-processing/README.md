# 220.video-processing - Video Processing

**Type:** Multimedia
**Languages:** Python
**Architecture:** x64, arm64

## Description

The benchmark implements two operations on video files: adding a watermark and creating a gif. Both input and output media are passed through the cloud storage. To process the video, the benchmark uses `ffmpeg`. The benchmark ships a static, glibc-based `ffmpeg` binary from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds). Since upstream builds expire, we archive it as the `spcleth/serverless-benchmarks:ffmpeg-reproducibility-archive-<version>` image with `tools/ffmpeg_archive.py`, which either copies a pinned BtbN release or, once that has expired, rebuilds the FFmpeg release tag with BtbN's scripts (tagged `-rebuild`). The image is pinned by digest in `init.sh`. We avoid musl-based builds: musl's `qsort` makes the `palettegen` filter used by `extract-gif` about 20-40% slower.

While 512 MB is technically sufficient and works well for the watermark operations, the `large` input converts the video into a gif which is more computationally intensive. On AWS, you should expect around ~30 seconds runtime on 1024 MiB allocation.

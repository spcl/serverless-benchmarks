#!/usr/bin/env bash
set -euo pipefail

# Pass through common args; provide sensible defaults
INPUT="${INPUT:-/data/sample.mp4}"
DURATION="${DURATION:-8}"
REPEAT="${REPEAT:-1}"
CSV="${CSV:-/out/results.csv}"
DECODE="${DECODE:-gpu}"   # 'gpu' or 'cpu'

mkdir -p /out

# If INPUT is missing, let gpu_bench synthesize one
/app/gpu_bench.py \
  --input "$INPUT" \
  --duration "$DURATION" \
  --repeat "$REPEAT" \
  --decode "$DECODE" \
  --csv "$CSV" \
  --trials \
    "codec=h264_nvenc,bitrate=5M,preset=p5" \
    "codec=h264_nvenc,bitrate=12M,preset=p1,scale=1920:1080" \
    "codec=hevc_nvenc,bitrate=6M,preset=p4"

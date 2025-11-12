#!/usr/bin/env bash
set -euo pipefail

# Default paths (mounted by SeBS local backend)
DATA_DIR="${DATA_DIR:-/data}"
OUT_DIR="${OUT_DIR:-/out}"

INPUT="${INPUT:-${DATA_DIR}/sample.mp4}"
WATERMARK="${WATERMARK:-${DATA_DIR}/watermark.png}"  # new line
DURATION="${DURATION:-8}"
REPEAT="${REPEAT:-1}"
CSV="${CSV:-${OUT_DIR}/results.csv}"
DECODE="${DECODE:-gpu}"   # 'gpu' or 'cpu'

mkdir -p "$OUT_DIR"

echo "==[ Video Watermarking GPU Benchmark ]=="
echo "Input:      $INPUT"
echo "Watermark:  $WATERMARK"
echo "Duration:   $DURATION s"
echo "Repeat:     $REPEAT"
echo "Decode:     $DECODE"
echo "Output CSV: $CSV"
echo

# If INPUT is missing, let gpu_bench synthesize one
/app/gpu_bench.py \
  --input "$INPUT" \
  --watermark "$WATERMARK" \     
  --duration "$DURATION" \
  --repeat "$REPEAT" \
  --decode "$DECODE" \
  --csv "$CSV" \
  --trials \
    "codec=h264_nvenc,bitrate=5M,preset=p5" \
    "codec=h264_nvenc,bitrate=12M,preset=p1,scale=1920:1080" \
    "codec=hevc_nvenc,bitrate=6M,preset=p4"

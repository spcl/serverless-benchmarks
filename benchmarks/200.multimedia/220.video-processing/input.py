# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
import glob
import os
import tempfile
import re
import subprocess
from pathlib import Path

def buckets_count():
    return (1, 1)

# We are using visual similarity (SSIM) for validating the output of video processing,
# as bitwise reproducibility is not guaranteed across different ffmpeg versions and hardware acceleration.
# Even for the same ffmpeg version, we can get slightly differnt outputs on different architectures,
# like x64 and arm64 on AWS, and across different clouds.
DEFAULT_SSIM_THRESHOLDS = {
    "mp4": 0.98,
    "gif": 0.98,
}
SSIM_RE = re.compile(r"\[Parsed_ssim.*?All:([\d.]+)")

OUTPUTS = {
    ('watermark', 1): Path('outputs', 'watermark_test.mp4'),
    ('watermark', 3): Path('outputs', 'watermark_small.mp4'),
    ('extract-gif', 2): Path('outputs', 'city.gif'),
}

'''
    Generate test, small and large workload for video processing.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
'''
def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    for file in glob.glob(os.path.join(data_dir, '*.mp4')):
        img = os.path.relpath(file, data_dir)
        upload_func(0, img, file)

    # Different operations for different sizes to test various video processing modes
    # Note: extract-gif can timeout on some configurations (long and heavy)
    size_configs = {
        'test': {'op': 'watermark', 'duration': 1},
        'small': {'op': 'watermark', 'duration': 3},
        'large': {'op': 'extract-gif', 'duration': 2},
    }

    config = size_configs.get(size, size_configs['test'])

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = "city.mp4"
    input_config['object']['op'] = config['op']
    input_config['object']['duration'] = config['duration']
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def compare_videos(
    result_path: Path,
    target_path: Path,
    is_gif: bool = False,
) -> str | None:
    """
    Run ffmpeg once computing SSIM, and PSNR.
    """
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    filter_complex = "[0:v][1:v]ssim"

    cmd = [
        ffmpeg, "-hide_banner", "-nostats",
        "-i", str(result_path),
        "-i", str(target_path),
        "-filter_complex", filter_complex,
        "-an",                # ignore audio
        "-f", "null", "-",    # discard output, we only want the filter metrics
    ]

    proc = subprocess.run(
        cmd, capture_output=True, text=True
    )

    if proc.returncode != 0:
        return f"Validation failed: ffmpeg run failed (exit {proc.returncode}):\n{proc.stderr}"

    ssim_match = SSIM_RE.search(proc.stderr)
    if not ssim_match:
        return f"Validation failed: could not parse SSIM from ffmpeg stderr:\n{proc.stderr}"

    ssim = float(ssim_match.group(1))

    ssim_threshold = DEFAULT_SSIM_THRESHOLDS['gif' if is_gif else 'mp4']
    if ssim < ssim_threshold:
        return f"Validation failed: SSIM {ssim:.4f} below threshold {ssim_threshold:.4f}"

    return None

def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:

    if data_dir is None:
        return "Data directory must be provided for output validation"

    result = output.get('result', {})
    key = result.get('key', '')

    if not isinstance(key, str) or len(key) == 0:
        return f"Output key is missing or invalid (type={type(key).__name__}, value='{key}')"

    if storage is None:
        return None

    bucket = input_config.get('bucket', {}).get('bucket', '')
    op = input_config.get('object', {}).get('op', '')
    duration = input_config.get('object', {}).get('duration', '')

    suffix = os.path.splitext(key)[1] or '.tmp'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        tmp_path = f.name

        try:
            storage.download(bucket, key, tmp_path)
            file_size = os.path.getsize(tmp_path)
            if file_size == 0:
                return f"Downloaded video output from storage is empty (bucket='{bucket}', key='{key}')"

            target_output = Path(data_dir) / OUTPUTS[(op, duration)]

            return compare_videos(target_output, Path(f.name), op == 'extract-gif')
        finally:
            os.unlink(tmp_path)

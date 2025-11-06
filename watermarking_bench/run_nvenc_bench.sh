#!/usr/bin/env bash
set -euo pipefail

# --- Config ---
BENCH_DIR="${HOME}/bench"
INPUT="${1:-${BENCH_DIR}/sample.mp4}"
DURATION="${DURATION:-8}"         # seconds per trial
REPEAT="${REPEAT:-1}"             # repeats per trial

mkdir -p "$BENCH_DIR"
cd "$BENCH_DIR"

echo "==[ NVENC Bench Repro ]=="
command -v nvidia-smi >/dev/null || { echo "nvidia-smi missing"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg missing"; exit 1; }
command -v python3 >/dev/null || { echo "python3 missing"; exit 1; }

echo "GPU:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
echo
echo "Encoders (ffmpeg):"
ffmpeg -hide_banner -encoders | grep -E 'nvenc|av1' || true
echo
echo "Filters (ffmpeg):"
ffmpeg -hide_banner -filters  | grep -E 'scale_(npp|cuda)|overlay_cuda' || true
echo

# --- Make or update a working gpu_bench.py (GPU-first, safe bridges, skip missing encoders) ---
cat > gpu_bench.py <<'PY'
#!/usr/bin/env python3
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile, csv
from typing import List, Dict, Any, Optional, Tuple

def which_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        sys.exit("ffmpeg not found on PATH. Use Docker image with NVENC or install FFmpeg with NVENC.")
    return p

def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def has_encoder(ffmpeg: str, enc: str) -> bool:
    out = run([ffmpeg, "-hide_banner", "-encoders"]).stdout
    return re.search(rf"\b{re.escape(enc)}\b", out) is not None

def has_filter(ffmpeg: str, name: str) -> bool:
    out = run([ffmpeg, "-hide_banner", "-filters"]).stdout
    return (f" {name} " in out)

def gpu_info() -> Dict[str, Any]:
    try:
        out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"]).stdout.strip()
        name, mem, drv = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"name": name, "memory_total_mb": int(mem), "driver_version": drv}
    except Exception:
        return {"name": None, "memory_total_mb": None, "driver_version": None}

def parse_progress(log: str) -> Dict[str, Any]:
    lines = [ln for ln in log.splitlines() if ("fps=" in ln or "speed=" in ln or "frame=" in ln)]
    fps = speed = frames = None
    if lines:
        last = lines[-1]
        m = re.search(r"fps=\s*([0-9]+(?:\.[0-9]+)?)", last);  fps = float(m.group(1)) if m else None
        m = re.search(r"speed=\s*([0-9]+(?:\.[0-9]+)?)x", last); speed = float(m.group(1)) if m else None
        m = re.search(r"frame=\s*([0-9]+)", last);              frames = int(m.group(1)) if m else None
    return {"fps": fps, "speed_x": speed, "frames": frames}

def build_vf_or_complex(ffmpeg: str, scale: Optional[str], wm_path: Optional[str], overlay: str, want_gpu_decode: bool) -> Tuple[List[str], str]:
    used = []
    vf_args: List[str] = []
    complex_graph = ""

    have_scale_npp    = has_filter(ffmpeg, "scale_npp")
    have_scale_cuda   = has_filter(ffmpeg, "scale_cuda")
    have_overlay_cuda = has_filter(ffmpeg, "overlay_cuda")

    if not wm_path:
        if scale:
            if want_gpu_decode and have_scale_npp:
                vf_args = ["-vf", f"scale_npp={scale}"]; used.append("scale_npp")
            elif want_gpu_decode and have_scale_cuda:
                vf_args = ["-vf", f"scale_cuda={scale}"]; used.append("scale_cuda")
            else:
                vf_args = ["-vf", f"hwdownload,format=nv12,scale={scale},hwupload_cuda"]
                used.append("scale(cpu)+hwdownload+hwupload_cuda")
        return (vf_args, "+".join(used))

    # watermark path
    if want_gpu_decode and have_overlay_cuda:
        if scale and have_scale_npp:
            complex_graph = f"[0:v]scale_npp={scale}[v0];[v0][1:v]overlay_cuda={overlay}[vout]"
            used += ["scale_npp","overlay_cuda"]
        elif scale and have_scale_cuda:
            complex_graph = f"[0:v]scale_cuda={scale}[v0];[v0][1:v]overlay_cuda={overlay}[vout]"
            used += ["scale_cuda","overlay_cuda"]
        elif scale:
            complex_graph = f"[0:v]hwdownload,format=nv12,scale={scale},hwupload_cuda[v0];[v0][1:v]overlay_cuda={overlay}[vout]"
            used += ["scale(cpu)+hwdownload+hwupload_cuda","overlay_cuda"]
        else:
            complex_graph = f"[0:v][1:v]overlay_cuda={overlay}[vout]"
            used += ["overlay_cuda"]
        return (["-filter_complex", complex_graph, "-map", "[vout]"], "+".join(used))

    # CPU overlay fallback (explicit bridges)
    if scale and want_gpu_decode and (have_scale_npp or have_scale_cuda):
        scaler = "scale_npp" if have_scale_npp else "scale_cuda"
        complex_graph = (
            f"[0:v]{scaler}={scale}[v0gpu];"
            f"[v0gpu]hwdownload,format=nv12[v0cpu];"
            f"[v0cpu][1:v]overlay={overlay}[mix];"
            f"[mix]hwupload_cuda[vout]"
        )
        used += [scaler, "hwdownload+overlay(cpu)+hwupload_cuda"]
    elif scale:
        complex_graph = (
            f"[0:v]hwdownload,format=nv12,scale={scale}[v0cpu];"
            f"[v0cpu][1:v]overlay={overlay}[mix];"
            f"[mix]hwupload_cuda[vout]"
        )
        used += ["scale(cpu)+overlay(cpu)+hwupload_cuda"]
    else:
        complex_graph = (
            f"[0:v]hwdownload,format=nv12[v0cpu];"
            f"[v0cpu][1:v]overlay={overlay}[mix];"
            f"[mix]hwupload_cuda[vout]"
        )
        used += ["overlay(cpu)+hwupload_cuda"]

    return (["-filter_complex", complex_graph, "-map", "[vout]"], "+".join(used))

def transcode_once(ffmpeg: str, inp: str, outp: str, codec: str, bitrate: str, preset: str,
                   duration: Optional[float], scale: Optional[str], wm_path: Optional[str],
                   overlay_pos: str, decode_mode: str = "gpu") -> Dict[str, Any]:

    if not has_encoder(ffmpeg, codec):
        raise RuntimeError(f"encoder '{codec}' not available; check your ffmpeg build (NVENC/AV1).")

    want_gpu_decode = (decode_mode == "gpu")
    args = [ffmpeg, "-hide_banner", "-y", "-vsync", "0"]

    if want_gpu_decode:
        args += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-extra_hw_frames", "16",
                 "-init_hw_device", "cuda=cuda", "-filter_hw_device", "cuda"]

    args += ["-i", inp]
    if wm_path:
        args += ["-loop", "1", "-i", wm_path]
    if duration:
        args += ["-t", str(duration)]

    filt_args, filter_used = build_vf_or_complex(ffmpeg, scale, wm_path, overlay_pos, want_gpu_decode)
    args += filt_args

    args += ["-c:v", codec, "-b:v", bitrate, "-preset", preset, "-rc", "vbr", "-movflags", "+faststart"]
    args += ["-c:a", "copy"]
    args += [outp]

    t0 = datetime.datetime.now()
    proc = run(args)
    t1 = datetime.datetime.now()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + proc.stdout + f"\n\nARGS:\n{' '.join(args)}")

    parsed = parse_progress(proc.stdout)
    size = os.path.getsize(outp) if os.path.exists(outp) else 0
    return {
        "args": args,
        "filter_used": filter_used,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-15:]),
        "compute_time_us": (t1 - t0) / datetime.timedelta(microseconds=1),
        "fps": parsed["fps"],
        "speed_x": parsed["speed_x"],
        "frames": parsed["frames"],
        "output_size_bytes": size
    }

def main():
    ap = argparse.ArgumentParser(description="GPU NVENC benchmark.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--warmup", action="store_true")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--watermark", default=None)
    ap.add_argument("--overlay", default="main_w/2-overlay_w/2:main_h/2-overlay_h/2")
    ap.add_argument("--decode", choices=["gpu","cpu"], default="gpu")
    ap.add_argument("--trials", nargs="+", default=[
        "codec=h264_nvenc,bitrate=5M,preset=p5",
        "codec=h264_nvenc,bitrate=12M,preset=p1,scale=1920:1080",
        "codec=hevc_nvenc,bitrate=6M,preset=p4",
        # "codec=av1_nvenc,bitrate=3M,preset=p5",  # only if available
    ])
    args = ap.parse_args()

    ffmpeg = which_ffmpeg()
    gi = gpu_info()

    def parse_trial(s: str) -> Dict[str, str]:
        d: Dict[str, str] = {}
        for kv in s.split(","):
            k, v = kv.split("=", 1); d[k.strip()] = v.strip()
        return d

    trial_specs = [parse_trial(s) for s in args.trials]

    # Warmup with first available encoder
    if args.warmup:
        warm = next((t for t in trial_specs if has_encoder(ffmpeg, t.get("codec","h264_nvenc"))), None)
        if warm:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
                _ = transcode_once(ffmpeg, args.input, tmp.name,
                                   warm.get("codec","h264_nvenc"),
                                   warm.get("bitrate","5M"),
                                   warm.get("preset","p5"),
                                   args.duration,
                                   warm.get("scale"),
                                   args.watermark,
                                   args.overlay,
                                   args.decode)

    results = []; idx = 0
    for spec in trial_specs:
        for _ in range(args.repeat):
            if not has_encoder(ffmpeg, spec.get("codec","h264_nvenc")):
                results.append({
                    "trial_index": idx, "codec": spec.get("codec"), "bitrate": spec.get("bitrate"),
                    "preset": spec.get("preset"), "scale_filter": "", "fps": None, "speed_x": None,
                    "frames": None, "compute_time_us": 0, "output_size_bytes": 0,
                    "stdout_tail": "SKIPPED: encoder not available", "argv": "", "status": "skipped"
                }); idx += 1; continue
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                outp = tmp.name
            res = transcode_once(ffmpeg, args.input, outp,
                                 spec.get("codec","h264_nvenc"),
                                 spec.get("bitrate","5M"),
                                 spec.get("preset","p5"),
                                 args.duration,
                                 spec.get("scale"),
                                 args.watermark,
                                 args.overlay,
                                 args.decode)
            results.append({
                "trial_index": idx, "codec": spec.get("codec"), "bitrate": spec.get("bitrate"),
                "preset": spec.get("preset"), "scale_filter": res["filter_used"], "fps": res["fps"],
                "speed_x": res["speed_x"], "frames": res["frames"],
                "compute_time_us": res["compute_time_us"], "output_size_bytes": res["output_size_bytes"],
                "stdout_tail": res["stdout_tail"], "argv": " ".join(res["args"]), "status": "ok"
            })
            idx += 1
            try: os.remove(outp)
            except OSError: pass

    report = {"gpu": gi, "ffmpeg_path": ffmpeg, "trial_count": len(results), "results": results}
    print(json.dumps(report, indent=2))

    if args.csv and results:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader(); w.writerows(results)

if __name__ == "__main__":
    main()
PY

chmod +x gpu_bench.py

# --- Provide a sample 4K clip if missing ---
if [[ ! -f "$INPUT" ]]; then
  echo "No input provided or file missing. Creating ${INPUT} (4K, 20s, tone + test pattern)..."
  ffmpeg -hide_banner -y \
    -f lavfi -i testsrc2=size=3840x2160:rate=30 \
    -f lavfi -i sine=frequency=1000:sample_rate=48000 \
    -t 20 \
    -c:v libx264 -pix_fmt yuv420p -b:v 600k \
    -c:a aac -b:a 96k \
    "$INPUT"
fi

# --- Run the benchmark ---
TS="$(date +%Y%m%d_%H%M%S)"
CSV="results_${TS}.csv"

echo
echo "Running GPU NVENC benchmark..."
./gpu_bench.py \
  --input "$INPUT" \
  --duration "$DURATION" \
  --repeat "$REPEAT" \
  --decode gpu \
  --csv "$CSV" \
  --trials \
    "codec=h264_nvenc,bitrate=5M,preset=p5" \
    "codec=h264_nvenc,bitrate=12M,preset=p1,scale=1920:1080" \
    "codec=hevc_nvenc,bitrate=6M,preset=p4"

echo
echo "Done. CSV saved at: $BENCH_DIR/$CSV"
echo "Preview:"
(head -n 1 "$CSV" && tail -n +2 "$CSV" | sed -n '1,3p') | sed 's/,/ | /g'

# NVENC-enabled FFmpeg base image
FROM jrottenberg/ffmpeg:6.1-nvidia

# Python for gpu_bench.py
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY gpu_bench.py /app/gpu_bench.py
COPY run.sh       /app/run.sh
RUN chmod +x /app/gpu_bench.py /app/run.sh

# default entrypoint lets SeBS simply "docker run" it
ENTRYPOINT ["/app/run.sh"]

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /function

# Copy benchmark code
COPY . /function/

# Compile CUDA microbenchmark
RUN nvcc -O3 -arch=sm_86 -o gpu_cache_bench gpu_cache_bench.cu

# If you need Python deps, add:
# RUN pip3 install -r requirements.txt

CMD ["python3", "handler.py"]
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# Install system dependencies needed for benchmarks
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all application files first
COPY . .

# Run benchmark init script if it exists (e.g., for ffmpeg in video-processing)
# This downloads static binaries needed by the benchmark
# Note: ignore errors from init.sh (e.g., when resources already exist)
RUN if [ -f "init.sh" ]; then \
        chmod +x init.sh && \
        ./init.sh /app verbose x64 || true; \
    fi

# Install dependencies
# Core dependencies for wrapper modules:
# - storage.py uses urllib (stdlib) to proxy R2 requests through worker.js
# - nosql.py, worker.py, handler.py use stdlib only
# Then install benchmark-specific requirements from requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Expose port 8080 for container communication
EXPOSE 8080

# Set environment variable for port
ENV PORT=8080

# Start the HTTP server
CMD ["python", "handler.py"]

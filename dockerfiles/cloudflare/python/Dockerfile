ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# Install system dependencies (ffmpeg for video processing benchmarks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all application files first
COPY . .

# Create ffmpeg directory and symlink for video-processing benchmark compatibility
RUN mkdir -p /app/ffmpeg && ln -s /usr/bin/ffmpeg /app/ffmpeg/ffmpeg

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

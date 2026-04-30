ARG BASE_IMAGE=node:18-slim
FROM ${BASE_IMAGE}

# Install system dependencies needed for benchmarks
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./

# Install dependencies
RUN npm install --production

# Copy all application files
COPY . .

# Run benchmark init script if it exists (e.g., for ffmpeg in video-processing)
# This downloads static binaries needed by the benchmark
# Note: ignore errors from init.sh (e.g., when resources already exist)
RUN if [ -f "init.sh" ]; then \
        chmod +x init.sh && \
        ./init.sh /app verbose x64 || true; \
    fi

# Expose port 8080 for container communication
EXPOSE 8080

# Set environment variable for port
ENV PORT=8080

# Start the HTTP server
CMD ["node", "handler.js"]

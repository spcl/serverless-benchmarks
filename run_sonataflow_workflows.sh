#!/bin/bash
set -euo pipefail

# Prepare local configuration files
if [ ! -f config/local_workflows.json ]; then
  cp config/example.json config/local_workflows.json
fi
if [ ! -f config/local_deployment.json ]; then
  cp config/example.json config/local_deployment.json
fi

DATA_FLAG="benchmarks-data/600.workflows/6100.1000-genome/ALL.chr21.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf"
if [ ! -f "$DATA_FLAG" ]; then
  echo "Workflow datasets missing, running download_datasets.sh..."
  (cd benchmarks-data/600.workflows && ./download_datasets.sh)
else
  echo "Workflow datasets present, skipping download."
fi

cleanup() {
  echo "Stopping all running Docker containers..."
  docker ps -q | xargs -r docker stop >/dev/null || true
}
trap cleanup EXIT

./sebs.py storage start all config/storage.json --output-json out_storage.json

MINIO_ADDRESS=$(jq -r '.object.minio.address' out_storage.json)
MINIO_PORT=$(jq -r '.object.minio.mapped_port' out_storage.json)
MINIO_ACCESS=$(jq -r '.object.minio.access_key' out_storage.json)
MINIO_SECRET=$(jq -r '.object.minio.secret_key' out_storage.json)
MINIO_INSTANCE=$(jq -r '.object.minio.instance_id' out_storage.json)
SCYLLA_ADDRESS=$(jq -r '.nosql.scylladb.address' out_storage.json)
SCYLLA_PORT=$(jq -r '.nosql.scylladb.mapped_port' out_storage.json)
SCYLLA_INSTANCE=$(jq -r '.nosql.scylladb.instance_id' out_storage.json)

for cfg in config/local_workflows.json config/local_deployment.json; do
  tmp=$(mktemp)
  jq \
    --arg addr "$MINIO_ADDRESS" \
    --argjson port "$MINIO_PORT" \
    --arg access "$MINIO_ACCESS" \
    --arg secret "$MINIO_SECRET" \
    --arg inst "$MINIO_INSTANCE" \
    --arg saddr "$SCYLLA_ADDRESS" \
    --argjson sport "$SCYLLA_PORT" \
    --arg sinst "$SCYLLA_INSTANCE" \
    --arg redis_host "localhost:6380" \
    --arg redis_pass "" \
    --arg runtime_url "http://localhost:8080" \
    --arg endpoint_prefix "services" \
    '(.deployment.name = "sonataflow")
     | (.deployment.sonataflow.storage.object.type = "minio")
     | (.deployment.sonataflow.storage.object.minio.address = $addr)
     | (.deployment.sonataflow.storage.object.minio.mapped_port = $port)
     | (.deployment.sonataflow.storage.object.minio.access_key = $access)
     | (.deployment.sonataflow.storage.object.minio.secret_key = $secret)
     | (.deployment.sonataflow.storage.object.minio.instance_id = $inst)
     | (.deployment.sonataflow.storage.object.minio.input_buckets = [])
     | (.deployment.sonataflow.storage.object.minio.output_buckets = [])
     | (.deployment.sonataflow.storage.nosql.type = "scylladb")
     | (.deployment.sonataflow.storage.nosql.scylladb.address = $saddr)
     | (.deployment.sonataflow.storage.nosql.scylladb.mapped_port = $sport)
     | (.deployment.sonataflow.storage.nosql.scylladb.instance_id = $sinst)
     | (.deployment.sonataflow.resources.redis.host = $redis_host)
     | (.deployment.sonataflow.resources.redis.password = $redis_pass)
     | (.deployment.sonataflow.resources.runtime.url = $runtime_url)
     | (.deployment.sonataflow.resources.runtime.endpoint_prefix = $endpoint_prefix)
    ' "$cfg" > "$tmp"
  mv "$tmp" "$cfg"
done

if docker ps -a --format '{{.Names}}' | grep -q '^sebs-redis$'; then
  docker rm -f sebs-redis >/dev/null
fi
docker run -d --name sebs-redis -p 6380:6379 redis:7

# Prepare SonataFlow workflow directory
SONATAFLOW_WORKFLOWS_DIR="$PWD/sonataflow-workflows"
mkdir -p "$SONATAFLOW_WORKFLOWS_DIR"

# Function to copy workflow definitions to SonataFlow directory after each benchmark
copy_workflows_to_sonataflow() {
  find cache -name "*.sw.json" -path "*/sonataflow/*" 2>/dev/null | while read -r swfile; do
    cp -f "$swfile" "$SONATAFLOW_WORKFLOWS_DIR/" 2>/dev/null || true
  done
}

# Create Docker network for SonataFlow and functions if it doesn't exist
docker network inspect sebs-network >/dev/null 2>&1 || docker network create sebs-network

# Note: We'll start SonataFlow runtime AFTER generating the first workflow
# so that it can detect workflows at startup and enable the processes generator

# Ensure native helper for selfish-detour is built before packaging
SELFISH_DIR="benchmarks/600.workflows/640.selfish-detour/python"
SELFISH_SRC="$SELFISH_DIR/selfish-detour.c"
SELFISH_SO="$SELFISH_DIR/selfish-detour.so"
if [ -f "$SELFISH_SRC" ]; then
  if [ ! -f "$SELFISH_SO" ] || [ "$SELFISH_SRC" -nt "$SELFISH_SO" ]; then
    echo "Compiling selfish-detour shared object..."
    gcc -O2 -shared -fPIC -o "$SELFISH_SO" "$SELFISH_SRC"
  fi
fi

WORKFLOWS=(
  "610.gen"
  "6100.1000-genome"
  "6101.1000-genome-individuals"
  "620.func-invo"
  "6200.trip-booking"
  "630.parallel-sleep"
  "631.parallel-download"
  "640.selfish-detour"
  "650.vid"
  "660.map-reduce"
  "670.auth"
  "680.excamera"
  "690.ml"
)

SONATAFLOW_STARTED=false
for wf in "${WORKFLOWS[@]}"; do
  echo "===== Running $wf ====="

  # First, create the workflow (without invoking it yet) by running with --repetitions 0
  # This generates the .sw.json file
  ./sebs.py benchmark workflow "$wf" test \
      --config config/local_workflows.json \
      --deployment sonataflow --trigger http --repetitions 0 \
      --output-dir results/local-workflows --verbose || true

  # Copy newly generated workflow definitions to SonataFlow directory
  copy_workflows_to_sonataflow
  echo "Copied workflow definitions to SonataFlow directory"

  # Start SonataFlow runtime on first iteration (after first workflow is generated)
  if [ "$SONATAFLOW_STARTED" = false ]; then
    echo "Starting SonataFlow runtime container..."
    if docker ps -a --format '{{.Names}}' | grep -q '^sonataflow-runtime$'; then
      docker rm -f sonataflow-runtime >/dev/null
    fi
    docker run -d --name sonataflow-runtime --network sebs-network -p 8080:8080 \
      -v "$SONATAFLOW_WORKFLOWS_DIR":/home/kogito/serverless-workflow-project/src/main/resources \
      quay.io/kiegroup/kogito-swf-devmode:latest

    echo "Waiting for SonataFlow runtime to start and load workflows..."
    sleep 20
    SONATAFLOW_STARTED=true
  else
    # Wait for SonataFlow to detect and load the new workflow (dev mode auto-reload)
    echo "Waiting for SonataFlow to load workflow..."
    sleep 10
  fi

  # Now run the actual benchmark
  ./sebs.py benchmark workflow "$wf" test \
      --config config/local_workflows.json \
      --deployment sonataflow --trigger http --repetitions 1 \
      --output-dir results/local-workflows --verbose || true

  sleep 5
done

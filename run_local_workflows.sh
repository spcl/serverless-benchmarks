#!/bin/bash
set -euo pipefail

# Prepare local configuration files
if [ ! -f config/local_workflows.json ]; then
  cp config/example.json config/local_workflows.json
fi
if [ ! -f config/local_deployment.json ]; then
  cp config/example.json config/local_deployment.json
fi

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
    '(.deployment.local.storage.object.minio.address = $addr)
     | (.deployment.local.storage.object.minio.mapped_port = $port)
     | (.deployment.local.storage.object.minio.access_key = $access)
     | (.deployment.local.storage.object.minio.secret_key = $secret)
     | (.deployment.local.storage.object.minio.instance_id = $inst)
     | (.deployment.local.storage.nosql.scylladb.address = $saddr)
     | (.deployment.local.storage.nosql.scylladb.mapped_port = $sport)
     | (.deployment.local.storage.nosql.scylladb.instance_id = $sinst)
    ' "$cfg" > "$tmp"
  mv "$tmp" "$cfg"
done

if docker ps -a --format '{{.Names}}' | grep -q '^sebs-redis$'; then
  docker rm -f sebs-redis >/dev/null
fi
docker run -d --name sebs-redis -p 6380:6379 redis:7

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

for wf in "${WORKFLOWS[@]}"; do
  echo "===== Running $wf ====="
  ./sebs.py benchmark workflow "$wf" test \
      --config config/local_workflows.json \
      --deployment local --trigger http --repetitions 1 \
      --output-dir results/local-workflows --verbose || true
  sleep 5
done

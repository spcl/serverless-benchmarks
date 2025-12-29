#!/bin/bash
set -euo pipefail

# Use a single Docker daemon for both SeBS (python docker SDK) and `docker` CLI.
# On Linux, prefer the native engine at `/var/run/docker.sock` when available:
# Docker Desktop's VM-backed filesystem sharing can break bind-mounted volumes for MinIO/ScyllaDB.
if [ -z "${DOCKER_HOST:-}" ]; then
  if [ -S /var/run/docker.sock ] && DOCKER_HOST=unix:///var/run/docker.sock docker info >/dev/null 2>&1; then
    export DOCKER_HOST="unix:///var/run/docker.sock"
  elif command -v docker >/dev/null 2>&1; then
    DOCKER_HOST_FROM_CONTEXT=$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)
    if [ -n "${DOCKER_HOST_FROM_CONTEXT:-}" ]; then
      export DOCKER_HOST="$DOCKER_HOST_FROM_CONTEXT"
    fi
  fi
fi

# Prefer the repo's virtualenv (avoids missing deps when not activated).
SEBS_PYTHON="${SEBS_PYTHON:-}"
if [ -z "${SEBS_PYTHON}" ]; then
  if [ -x "$PWD/python-venv/bin/python" ]; then
    SEBS_PYTHON="$PWD/python-venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    SEBS_PYTHON="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    SEBS_PYTHON="$(command -v python)"
  else
    echo "ERROR: python not found (set SEBS_PYTHON or install python3)."
    exit 1
  fi
fi

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

RUNTIME_URL="http://localhost:8080"
# Recent `quay.io/kiegroup/kogito-swf-devmode` images expose workflow endpoints at `/{workflowId}`.
# Some older setups used `/services/{workflowId}`; SeBS will auto-fallback on 404.
ENDPOINT_PREFIX=""

cleanup() {
  echo "Stopping all running Docker containers..."
  docker ps -q | xargs -r docker stop >/dev/null || true
}
trap cleanup EXIT

"$SEBS_PYTHON" ./sebs.py storage start all config/storage.json --output-json out_storage.json

MINIO_ADDRESS=$(jq -r '.object.minio.address' out_storage.json)
MINIO_PORT=$(jq -r '.object.minio.mapped_port' out_storage.json)
MINIO_ACCESS=$(jq -r '.object.minio.access_key' out_storage.json)
MINIO_SECRET=$(jq -r '.object.minio.secret_key' out_storage.json)
MINIO_INSTANCE=$(jq -r '.object.minio.instance_id' out_storage.json)
SCYLLA_ADDRESS=$(jq -r '.nosql.scylladb.address' out_storage.json)
SCYLLA_PORT=$(jq -r '.nosql.scylladb.mapped_port' out_storage.json)
SCYLLA_INSTANCE=$(jq -r '.nosql.scylladb.instance_id' out_storage.json)

# Fail fast if storage containers were created in a different daemon/context.
if ! docker inspect "$MINIO_INSTANCE" >/dev/null 2>&1; then
  echo "ERROR: MinIO container $MINIO_INSTANCE not found in the current Docker daemon."
  echo "Hint: set DOCKER_HOST to the daemon SeBS uses (e.g., unix:///var/run/docker.sock)."
  exit 1
fi
if ! docker inspect "$SCYLLA_INSTANCE" >/dev/null 2>&1; then
  echo "ERROR: ScyllaDB container $SCYLLA_INSTANCE not found in the current Docker daemon."
  echo "Hint: set DOCKER_HOST to the daemon SeBS uses (e.g., unix:///var/run/docker.sock)."
  exit 1
fi

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
    --arg runtime_url "$RUNTIME_URL" \
    --arg endpoint_prefix "$ENDPOINT_PREFIX" \
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

# Prepare SonataFlow resources directory structure expected by kogito-swf-devmode:
# - `src/main/resources/application.properties`
# - `src/main/resources/workflows/*.sw.json`
SONATAFLOW_RESOURCES_DIR="$PWD/sonataflow-workflows"
SONATAFLOW_WORKFLOWS_DIR="$SONATAFLOW_RESOURCES_DIR/workflows"
mkdir -p "$SONATAFLOW_WORKFLOWS_DIR"
if [ ! -f "$SONATAFLOW_RESOURCES_DIR/application.properties" ]; then
  cat >"$SONATAFLOW_RESOURCES_DIR/application.properties" <<'EOF'
# Enable Kogito process/workflow generation
kogito.codegen.processes.enabled=true
quarkus.kogito.codegen.processes.enabled=true
EOF
fi

# Read the runtime settings so we only stage matching workflow variants.
RUNTIME_LANG=$(jq -r '.experiments.runtime.language // "python"' config/local_workflows.json)
RUNTIME_VER=$(jq -r '.experiments.runtime.version // "3.11"' config/local_workflows.json)
ARCH=$(jq -r '.experiments.architecture // "x64"' config/local_workflows.json)

dedupe_sw_files() {
  local dir=$1
  declare -A seen=()
  # Consider any `.sw.json` under resources (root + workflows/) to avoid Quarkus duplicates.
  while IFS= read -r -d '' f; do
    local wid
    wid=$(jq -r '.id // empty' "$f" 2>/dev/null || true)
    [ -n "$wid" ] || continue
    if [ -n "${seen[$wid]:-}" ] && [ "${seen[$wid]}" != "$f" ]; then
      echo "Removing duplicate workflow id '$wid' at $f (keeping ${seen[$wid]})"
      rm -f "$f"
    else
      seen[$wid]="$f"
    fi
  done < <(find "$dir" -maxdepth 2 -name "*.sw.json" -print0 2>/dev/null)
}

# If older runs put `.sw.json` in the resources root, move them into `workflows/`
# so Quarkus only sees a single copy.
while IFS= read -r -d '' f; do
  mv -f "$f" "$SONATAFLOW_WORKFLOWS_DIR/" || true
done < <(find "$SONATAFLOW_RESOURCES_DIR" -maxdepth 1 -name "*.sw.json" -print0 2>/dev/null)
dedupe_sw_files "$SONATAFLOW_RESOURCES_DIR"

# Function to copy workflow definitions to SonataFlow directory after each benchmark
copy_workflows_to_sonataflow() {
  find cache -name "*.sw.json" \
    -path "*/sonataflow/${RUNTIME_LANG}/${RUNTIME_VER}/${ARCH}/*" \
    -path "*/workflow_resources/sonataflow/*" 2>/dev/null | while read -r swfile; do
    cp -f "$swfile" "$SONATAFLOW_WORKFLOWS_DIR/" 2>/dev/null || true
  done
  dedupe_sw_files "$SONATAFLOW_RESOURCES_DIR"
}

get_workflow_id_for() {
  local wf_name=$1
  local pattern="${wf_name//./_}"
  for f in "$SONATAFLOW_WORKFLOWS_DIR"/*.sw.json; do
    [ -f "$f" ] || continue
    if printf '%s\n' "$f" | grep -q "$pattern"; then
      jq -r '.id' "$f"
      return 0
    fi
  done
  local newest
  newest=$(ls -1t "$SONATAFLOW_WORKFLOWS_DIR"/*.sw.json 2>/dev/null | head -n1)
  if [ -n "$newest" ]; then
    jq -r '.id' "$newest"
    return 0
  fi
  return 1
}

wait_for_health() {
  local url=$1
  local attempts=40
  local delay=3
  echo "Waiting for SonataFlow runtime health at $url ..."
  for i in $(seq 1 $attempts); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "$url/q/health/ready" || true)
    if [ "$code" = "200" ]; then
      echo "SonataFlow runtime is ready."
      return 0
    fi
    sleep "$delay"
  done
  echo "Warning: SonataFlow runtime health endpoint not ready after $((attempts * delay))s"
}

wait_for_workflow_endpoint() {
  local workflow_id=$1
  local base_url=$2
  local endpoint_prefix=$3
  local prefix="${endpoint_prefix#/}"
  local -a urls=()
  if [ -n "$prefix" ]; then
    urls+=("${base_url%/}/${prefix}/${workflow_id}")
  fi
  urls+=("${base_url%/}/${workflow_id}")
  if [ "$prefix" != "services" ]; then
    urls+=("${base_url%/}/services/${workflow_id}")
  fi
  local attempts=40
  local delay=3
  echo "Waiting for workflow endpoint(s): ${urls[*]} ..."
  for i in $(seq 1 $attempts); do
    for url in "${urls[@]}"; do
      # GET will likely return 405 for POST-only endpoints; 404 means not loaded yet
      code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)
      if [ "$code" != "404" ] && [ "$code" != "000" ]; then
        echo "Workflow endpoint responding at $url with HTTP $code."
        return 0
      fi
    done
    sleep "$delay"
  done
  echo "Warning: Workflow endpoint(s) not responding after $((attempts * delay))s"
}

preflight_runtime_function_connectivity() {
  local sw_json=$1
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^sonataflow-runtime$'; then
    return 0
  fi
  if ! command -v jq >/dev/null 2>&1; then
    return 0
  fi
  if [ ! -f "$sw_json" ]; then
    return 0
  fi

  # Extract function base URLs from `rest:post:http://host:port/` operations.
  mapfile -t urls < <(jq -r '.functions[]?.operation // empty' "$sw_json" 2>/dev/null \
    | sed -n 's#^rest:post:##p' | sed -e 's#/*$#/#' | sort -u)
  if [ "${#urls[@]}" -eq 0 ]; then
    return 0
  fi

  echo "Preflight: checking SonataFlow runtime connectivity to function containers..."
  # Try curl first, then wget, then python.
  local http_cmd
  http_cmd=$(docker exec sonataflow-runtime sh -lc 'if command -v curl >/dev/null 2>&1; then echo curl; elif command -v wget >/dev/null 2>&1; then echo wget; elif command -v python3 >/dev/null 2>&1; then echo python3; elif command -v python >/dev/null 2>&1; then echo python; else echo none; fi' 2>/dev/null || echo none)
  if [ "$http_cmd" = "none" ]; then
    echo "Preflight skipped: no curl/wget/python found inside sonataflow-runtime."
    return 0
  fi
  local failed=0
  for u in "${urls[@]}"; do
    # Use `/alive` which SeBS function containers expose.
    if [ "$http_cmd" = "curl" ]; then
      docker exec sonataflow-runtime sh -lc "curl -fsS --max-time 3 '${u}alive' >/dev/null" >/dev/null 2>&1 || failed=1
    elif [ "$http_cmd" = "wget" ]; then
      docker exec sonataflow-runtime sh -lc "wget -q -T 3 -O - '${u}alive' >/dev/null" >/dev/null 2>&1 || failed=1
    else
      docker exec sonataflow-runtime sh -lc "$http_cmd - <<'PY'\nimport sys, urllib.request\nurl=sys.argv[1]\nurllib.request.urlopen(url, timeout=3).read(1)\nPY\n'${u}alive'" >/dev/null 2>&1 || failed=1
    fi
    if [ "$failed" -ne 0 ]; then
      echo "  Cannot reach ${u}alive from sonataflow-runtime"
    fi
  done
  if [ "$failed" -ne 0 ]; then
    echo "Preflight failed: SonataFlow cannot reach one or more function containers."
    echo "Hint: ensure sonataflow-runtime and sebd-*___* function containers share a Docker network, and that SeBS and docker CLI use the same Docker daemon/context."
    return 1
  fi
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
  # "6101.1000-genome-individuals"
  # "620.func-invo"
  # "6200.trip-booking"
  # "630.parallel-sleep"
  # "631.parallel-download"
  # "640.selfish-detour"
  # "650.vid"
  # "660.map-reduce"
  # "670.auth"
  # "680.excamera"
  # "690.ml"
)

SONATAFLOW_STARTED=false
for wf in "${WORKFLOWS[@]}"; do
  echo "===== Running $wf ====="

  # First, create the workflow (without invoking it yet) by running with --repetitions 0
  # This generates the .sw.json file
  "$SEBS_PYTHON" ./sebs.py benchmark workflow "$wf" test \
      --config config/local_workflows.json \
      --deployment sonataflow --trigger http --repetitions 0 \
      --output-dir results/local-workflows --verbose || true

  # Copy newly generated workflow definitions to SonataFlow directory
  copy_workflows_to_sonataflow
  echo "Copied workflow definitions to SonataFlow directory"

  if ! ls "$SONATAFLOW_WORKFLOWS_DIR"/*.sw.json >/dev/null 2>&1; then
    echo "No workflow definitions found in $SONATAFLOW_WORKFLOWS_DIR after generating $wf"
    exit 1
  fi

  WF_ID=$(get_workflow_id_for "$wf" || true)
  if [ -z "$WF_ID" ] || [ "$WF_ID" = "null" ]; then
    echo "Could not determine workflow id for $wf; available definitions:"
    ls -l "$SONATAFLOW_WORKFLOWS_DIR"
    exit 1
  fi
  echo "Workflow id for $wf: $WF_ID"

  # Start SonataFlow runtime on first iteration (after first workflow is generated)
  if [ "$SONATAFLOW_STARTED" = false ]; then
    echo "Starting SonataFlow runtime container..."
    if docker ps -a --format '{{.Names}}' | grep -q '^sonataflow-runtime$'; then
      docker rm -f sonataflow-runtime >/dev/null
    fi
    # Start on `sebs-network` (primary) and also attach to `bridge` so the runtime can reach
    # function containers whether SeBS exposes them via `sebs-network` or `bridge`.
    docker run -d --name sonataflow-runtime --network sebs-network -p 8080:8080 \
      -v "$SONATAFLOW_RESOURCES_DIR":/home/kogito/serverless-workflow-project/src/main/resources \
      quay.io/kiegroup/kogito-swf-devmode:latest
    docker network connect bridge sonataflow-runtime >/dev/null 2>&1 || true

    echo "Waiting for SonataFlow runtime to start and load workflows..."
    wait_for_health "$RUNTIME_URL"
    wait_for_workflow_endpoint "$WF_ID" "$RUNTIME_URL" "$ENDPOINT_PREFIX"
    SONATAFLOW_STARTED=true
  else
    # Wait for SonataFlow to detect and load the new workflow (dev mode auto-reload)
    echo "Waiting for SonataFlow to load workflow..."
    sleep 10
    wait_for_workflow_endpoint "$WF_ID" "$RUNTIME_URL" "$ENDPOINT_PREFIX"
  fi

  # Ensure runtime can reach function containers before invoking the workflow.
  preflight_runtime_function_connectivity "$SONATAFLOW_WORKFLOWS_DIR/${WF_ID}.sw.json" || exit 1

  # Now run the actual benchmark
  "$SEBS_PYTHON" ./sebs.py benchmark workflow "$wf" test \
      --config config/local_workflows.json \
      --deployment sonataflow --trigger http --repetitions 1 \
      --output-dir results/local-workflows --verbose || true

  sleep 5
done

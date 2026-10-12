#!/usr/bin/env bash

#rm -rf ../sebs-virtualenv
#rm -rf ../sebs-build

# remove all runner processes
echo "Stopping memory analyzers..."
pkill -9 -f proc_analyzer.py

# stop all docker containers started by SeBS, matched by image name
# since image tags differ between versions
stop_containers() {
  local ids
  ids=$(docker ps --format '{{.ID}} {{.Image}}' | grep -E " ($1)" | cut -d' ' -f1)
  if [[ -n "${ids}" ]]; then
    docker stop -t0 ${ids} > /dev/null
  fi
}

echo "Stopping local function containers..."
stop_containers 'spcleth/serverless-benchmarks:run\.local\.'
echo "Stopping storage containers..."
stop_containers 'rustfs/rustfs:|spcleth/serverless-benchmarks:minio-|minio/minio:|scylladb/scylla:'

#!/bin/bash

#rm -rf ../sebs-virtualenv
#rm -rf ../sebs-build

# remove all runner processes
echo "Stopping memory analyzers..."
pkill -9 -f proc_analyzer.py

# stop all docker containers
# TODO: create common ancestor for all runtimes
echo "Stopping Docker containers..."
for name in "nodejs.13.6" "python.3.6"; do
  active_containers=$(docker ps --filter ancestor=sebs.run.local.${name} -q)
  if [[ -n "${active_containers}" ]]; then
    docker stop -t0 ${active_containers} > /dev/null
  fi
done
echo "Stopping minio storage containers..."
active_containers=$(docker ps --filter ancestor=minio/minio -q)
if [[ -n "${active_containers}" ]]; then
  docker stop -t0 ${active_containers} > /dev/null
fi


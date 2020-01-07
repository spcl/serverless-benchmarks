#!/bin/bash

#rm -rf ../sebs-virtualenv
#rm -rf ../sebs-build

# remove all runner processes
echo "Stopping memory analyzers..."
pkill -9 -f mem_analyzer.py

# stop all docker containers
# TODO: create common ancestor for all runtimes
echo "Stopping Docker containers..."
active_containers=$(docker ps --filter ancestor=sebs-local-python -q)
if [[ -n "${active_containers}" ]]; then
  docker stop -t0 ${active_containers}
fi


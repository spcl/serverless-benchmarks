#!/bin/bash

export DOCKER_HOST_IP=$(route -n | awk '/UG[ \t]/{print $2}')
EXPERIMENT_INPUT="$1"
file_name=logs/execution_00.log
counter=0

while [ -e "${file_name}" ]; do
  counter=$((counter + 1))
  file_name=$(printf '%s_%02d.log' "logs/execution" "$(( counter ))")
done

script -e -c "python3 runner.py ${EXPERIMENT_INPUT}" -f "${file_name}"

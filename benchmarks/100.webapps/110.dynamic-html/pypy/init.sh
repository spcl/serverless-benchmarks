#!/bin/bash

DIR=$1
VERBOSE=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
path="${SCRIPT_DIR}/templates/"
if [ "$VERBOSE" = true ]; then
  echo "Update ${DIR} with static templates ${path}"
fi
cp -r ${SCRIPT_DIR}/templates ${DIR}

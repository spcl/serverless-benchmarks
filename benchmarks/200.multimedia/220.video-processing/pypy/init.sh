#!/bin/bash

DIR=$1
VERBOSE=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
path="${SCRIPT_DIR}/../init.sh"
if [ "$VERBOSE" = true ]; then
  echo "Update ${DIR} with init script ${path}"
fi
bash ${path} ${DIR} ${VERBOSE}

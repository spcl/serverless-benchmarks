#!/bin/bash

DIR=$1
VERBOSE=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
path="${SCRIPT_DIR}/imagenet_class_index.json"
if [ "$VERBOSE" = true ]; then
  echo "Update ${DIR} with json ${path}"
fi
cp ${path} ${DIR}

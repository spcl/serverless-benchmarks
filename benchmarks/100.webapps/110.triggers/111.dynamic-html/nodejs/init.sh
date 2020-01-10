#!/bin/bash

ZIP_FILE=$1
VERBOSE=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
path="${SCRIPT_DIR}/templates/"
if [ "$VERBOSE" = true ]; then
  echo "Update ${ZIP_FILE} with static templates ${path}"
fi
pushd ${SCRIPT_DIR} > /dev/null
zip -qu ${ZIP_FILE} templates/*
popd > /dev/null

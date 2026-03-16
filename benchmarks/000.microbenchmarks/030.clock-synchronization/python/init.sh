# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
#!/bin/bash

DIR=$1
VERBOSE=$2
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cp "${SCRIPT_DIR}/file" "${DIR}"

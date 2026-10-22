#!/bin/bash
# Copyright 2020-2026 ETH Zurich and the SeBS authors. All rights reserved.
set -euo pipefail

DIR=$1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# SeBS copies *.py and requirements.txt* itself. Add the remaining build assets.
cp "${SCRIPT_DIR}/Dockerfile" "${DIR}/Dockerfile"
mkdir -p "${DIR}/patches"
cp "${SCRIPT_DIR}/patches/"*.patch "${DIR}/patches/"

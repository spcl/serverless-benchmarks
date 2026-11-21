#!/bin/bash
# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

# SeBS copies only the top-level .cs and .csproj files of a .NET benchmark. Copy the
# templates next to function.csproj, which embeds them into the assembly.
DIR=$1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cp -r "${SCRIPT_DIR}/templates" "${DIR}"

#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cc -O2 -fPIC -shared "$SCRIPT_DIR/selfish-detour.c" -o "$SCRIPT_DIR/selfish-detour.so"

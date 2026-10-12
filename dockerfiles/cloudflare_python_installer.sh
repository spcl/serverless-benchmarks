#!/bin/bash
set -e

cd /mnt/function

if [ -f pyproject.toml ]; then
    python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"
    pywrangler --version
fi

touch .build-validated

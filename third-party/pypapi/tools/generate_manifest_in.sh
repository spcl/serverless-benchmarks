#!/bin/bash

##
## Lists the files to include in sdist distribution. This can be used to
## generate the MANIFEST.in contents:
##
##     tools/generate_manifest_in.sh > MANIFEST.in
##

cd papi/src > /dev/null
make clean > /dev/null
cd - > /dev/null

echo "include README.md"
echo "include README.rst"

echo

find pypapi -name "*.h" -exec echo "include" "{}" ";"

echo

find papi -type f -exec echo "include" "{}" ";"

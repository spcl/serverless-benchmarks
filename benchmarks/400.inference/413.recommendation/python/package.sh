#!/bin/bash

PACKAGE_DIR=$1
echo "DLRM GPU package size $(du -sh $1 | cut -f1)"

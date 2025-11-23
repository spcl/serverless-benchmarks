#!/bin/bash

# Arguments required by SeBS, even if unused
DIR=$1
VERBOSE=$2
TARGET_ARCHITECTURE=$3

# This benchmark does not need any special init step.
# All dependencies (torch, opencv-python, etc.) are installed via requirements.txt.
exit 0

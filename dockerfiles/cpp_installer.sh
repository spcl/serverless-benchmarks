#!/bin/bash

mkdir -p /mnt/function/build
cmake3 -DCMAKE_BUILD_TYPE=Release -S /mnt/function/ -B /mnt/function/build >/mnt/function/build/configuration.log || {
  echo "CMake configuration failed. Check configuration.log for details." >&2
  exit 1
}
VERBOSE=1 cmake3 --build /mnt/function/build --target aws-lambda-package-benchmark >/mnt/function/build/compilation.log || {
  echo "CMake build failed. Check compilation.log for details." >&2
  exit 1
}

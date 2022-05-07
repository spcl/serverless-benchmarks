#!/bin/bash


cmake3 -DCMAKE_BUILD_TYPE=Release -S /mnt/function/ -B /mnt/function/build
cmake3 --build /mnt/function/build --target aws-lambda-package-benchmark


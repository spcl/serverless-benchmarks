#!/bin/bash
set -e

cd /mnt/function

npm install --production
npm install --force esbuild

node build.js
node postprocess.js

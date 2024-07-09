#!/bin/bash

if [ -f $FILE ]; then
  . /nvm/nvm.sh
fi
cd /mnt/function && npm install && rm -rf package-lock.json

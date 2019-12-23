#!/bin/bash
ts=$(date +%s%N);
python3 -c "from json import load; from function import handler;handler(load(open('input.json', 'r')))"
tt=$((($(date +%s%N) - $ts)/1000)) ; echo $tt

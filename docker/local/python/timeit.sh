#!/bin/bash
#ts=$(date +%s%N);
export TIMEFORMAT='%3R,%3U,%3S'
time python3 -c "from json import load; from function import function; print(function.handler(load(open('input.json', 'r'))))" > $1
#tt=$((($(date +%s%N) - $ts)/1000)) ; echo $tt

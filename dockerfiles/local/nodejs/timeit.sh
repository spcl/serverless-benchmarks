#!/bin/bash
OUT=$1
#ts=$(date +%s%N);
export TIMEFORMAT='%3R,%3U,%3S'
time node --expose-gc -e "var fs = require('fs'), f = require('./function/function');
async function test() {
  var input = JSON.parse(fs.readFileSync('input.json', 'utf-8'));
  return await f.handler(input);
}
test().then( (data) => console.log(data) );" > $OUT
#tt=$((($(date +%s%N) - $ts)/1000)) ; echo $tt

#!/bin/bash
ts=$(date +%s%N);
node -e "var fs = require('fs'), f = require('./function');
async function test() {
  var input = JSON.parse(fs.readFileSync('input.json', 'utf-8'));
  return await f.handler(input);
}
test()"
tt=$((($(date +%s%N) - $ts)/1000)) ; echo $tt

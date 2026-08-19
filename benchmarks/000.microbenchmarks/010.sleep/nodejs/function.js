// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
const timer = ms => new Promise( res => setTimeout(res, ms));

exports.handler = async function(event) {
  var sleep =  event.sleep;
  var start = process.hrtime();
  await timer(sleep*1000);
  var elapsed = process.hrtime(start);
  return {result: elapsed[0] + elapsed[1] / 1e9};
};

// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
const timer = ms => new Promise( res => setTimeout(res, ms));

exports.handler = async function(event) {
  var sleep =  event.sleep;
  timer(sleep*1000);
  return sleep;
};

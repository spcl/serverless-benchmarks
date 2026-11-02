// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const environment = require('./function/environment');

function process_output(data, http_trigger) {
  if(http_trigger)
    return JSON.stringify(data);
  else
    return data;
}

exports.handler = async function(event, context) {
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var http_trigger = "body" in event;
  var input_data = http_trigger ? JSON.parse(event.body) : event
  var func = require('./function/function')
  var ret = func.handler(input_data);
  return ret.then(
    (result) => {
      var elapsed = process.hrtime(start);
      var end = Date.now()/1000;
      var micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;

      var env = environment.collect();
      return {
        statusCode: 200,
        body: process_output({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: result,
          is_cold: 'static' in env,
          request_id: context.awsRequestId,
          environment: env
        }, http_trigger)
      };
    },
    (error) => {
      throw(error);
    }
  );
}


const path = require('path'), fs = require('fs');

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

      var is_cold = false;
      var fname = path.join('/tmp','cold_run');
      if(!fs.existsSync(fname)) {
        is_cold = true;
        fs.closeSync(fs.openSync(fname, 'w'));
      }
      return {
        statusCode: 200,
        body: process_output({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: {output: result},
          is_cold: is_cold,
          request_id: context.awsRequestId
        }, http_trigger)
      };
    },
    (error) => {
      throw(error);
    }
  );
}

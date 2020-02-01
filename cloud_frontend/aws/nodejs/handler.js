
const path = require('path'), fs = require('fs');

exports.handler = async function(event, context) {
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var func = require('./function/function')
  var ret = func.handler(event);
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
        body: {
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: result,
          is_cold: is_cold,
          request_id: context.awsRequestId
        }
      };
    },
    (error) => {
      throw(error);
    }
  );
}

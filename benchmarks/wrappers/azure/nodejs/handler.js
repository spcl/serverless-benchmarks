

const path = require('path'), fs = require('fs');

module.exports = async function(context, req) {
  if('connection_string' in req.body) {
    process.env['STORAGE_CONNECTION_STRING'] = req.body.connection_string
  }
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var func = require('./function');
  var ret = func.handler(req.body);
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
          body: {
            begin: begin,
            end: end,
            compute_time: micro,
            results_time: 0,
            result: {output: result},
            is_cold: is_cold,
            request_id: context.invocationId
          },
          headers: { 'Content-Type': 'application/json' }
      };
      // required only for runtime V1
      //context.done();
    },
    (error) => {
      throw(error);
    }
  );
}

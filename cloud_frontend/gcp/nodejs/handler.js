
const path = require('path'), fs = require('fs');

exports.handler = async function(req, res) {
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var func = require('./function')
  var ret = func.handler(req);
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

      res.status(200).json({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: result,
          is_cold: is_cold,
          request_id: begin // FIXME: How to determine request_id without context?
        });
    },
    (error) => {
      throw(error);
    }
  );
}

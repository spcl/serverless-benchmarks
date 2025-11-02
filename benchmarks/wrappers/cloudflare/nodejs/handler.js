
const path = require('path'), fs = require('fs');

export default {
    async fetch(request, env, ctx) {
    var begin = Date.now()/1000;
    var start = process.hrtime();
    var func = require('./function')
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

      res.status(200).json({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: {output: result},
          is_cold: is_cold,
          request_id: req.headers["function-execution-id"]
        });
    },
    (error) => {
      throw(error);
    }
  );
}

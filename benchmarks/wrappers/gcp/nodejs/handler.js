// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const environment = require('./function/environment');

if('NOSQL_STORAGE_DATABASE' in process.env) {
  const nosql = require('./function/nosql');
  nosql.nosql.get_instance(process.env['NOSQL_STORAGE_DATABASE']);
}

exports.handler = async function(req, res) {
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var requestId = req.headers["x-cloud-trace-context"] || req.headers["function-execution-id"];
  var func = require('./function/function')
  var ret = func.handler(req.body);
  return ret.then(
    (result) => {
      var elapsed = process.hrtime(start);
      var end = Date.now()/1000;
      var micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;
      var env = environment.collect();

      res.status(200).json({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: result,
          is_cold: 'static' in env,
          request_id: requestId,
          environment: env
        });
    },
    (error) => {
      throw(error);
    }
  );
}

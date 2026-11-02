// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const environment = require('./environment');

if('NOSQL_STORAGE_DATABASE' in process.env) {
  const nosql = require('./nosql');
  nosql.nosql.get_instance(
    process.env['NOSQL_STORAGE_DATABASE'],
    process.env['NOSQL_STORAGE_URL'],
    process.env['NOSQL_STORAGE_CREDS']
  );
}

module.exports = async function(context, req) {
  var begin = Date.now()/1000;
  var start = process.hrtime();
  var func = require('./function');
  var ret = func.handler(req.body);
  return ret.then(
    (result) => {
      var elapsed = process.hrtime(start);
      var end = Date.now()/1000;
      var micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;
      var env = environment.collect();

      return {
          body: {
            begin: begin,
            end: end,
            compute_time: micro,
            results_time: 0,
            result: result,
            is_cold: 'static' in env,
            request_id: context.invocationId,
            environment: env
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

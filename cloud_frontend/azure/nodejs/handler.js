


module.exports = async function(context, req) {
  if('connection_string' in req.body) {
    process.env['STORAGE_CONNECTION_STRING'] = req.body.connection_string
  }
  var start = process.hrtime();
  var func = require('./function');
  var ret = func.handler(req.body);
  return ret.then(
    (result) => {
      var elapsed = process.hrtime(start);
      var micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;
      return {
          body: {compute_time: micro, results_time: 0, result: result},
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

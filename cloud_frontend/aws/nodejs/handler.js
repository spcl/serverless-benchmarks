

exports.handler = async function(event, context) {
  var start = process.hrtime();
  var func = require('./function/function')
  var ret = func.handler(event);
  return ret.then(
    (result) => {
      var elapsed = process.hrtime(start);
      var micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;
      return {compute_time: micro, results_time: 0, result: result};
    },
    (error) => {
      throw(error);
    }
  );
}

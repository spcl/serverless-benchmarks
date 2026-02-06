
const glob = require('glob'),
      path = require('path');

const RESULTS_DIR = 'results';
exports.RESULTS_DIR = RESULTS_DIR;
const LOGS_DIR = 'logs';
exports.LOGS_DIR = LOGS_DIR;


exports.get_config = function () {
  return {
    name: 'nodejs',
    version: process.version,
    modules: process.moduleLoadList
  };
}

exports.start_benchmarking = function() {
  return Date.now()
}

exports.stop_benchmarking = function() {
  return Date.now()
}

exports.get_result_prefix = function(dirname, name, suffix) {
  name = path.join(dirname, name);
  let counter = 0
  while(
    glob.sync(
      name + '_' + counter.toString().padStart(2, '0') + '*.' + suffix
    ).length
  ) {
    counter += 1
  }
  // util.format ignores padding zeroes
  return name + '_' + counter.toString().padStart(2, '0') + '.' + suffix
}

exports.process_timestamps = function(timestamps) {

}



const tools = require('./tools'),
    fs = require('fs'),
    strftime = require('strftime'),
    f = require('./function/function'),
    util = require('util');
const createCsvWriter = require('csv-writer').createArrayCsvWriter;

let cfg = JSON.parse(fs.readFileSync(process.argv[2]));
let repetitions = cfg.benchmark.repetitions;
let disable_gc = cfg.benchmark.disable_gc;
let input_data = cfg.input;
let timedata = new Array(repetitions);
process.on('unhandledRejection', r => console.log(r));

// Due to the async nature of nodejs, we use 'then' functionality
// of promise to make sure that we start a new instance only after finishing
// the previous one. There's no other option to achieve true waiting and we don't
// want to start multiple instances and let them work concurrently.
let measurer = async function(repetition, finish) {
  if (repetition < repetitions) {
    let begin_timestamp = Date.now();
    let begin = process.hrtime();
    let cpuTimeBegin = process.cpuUsage();
    let ret = f.handler(input_data);
    ret.then((res) => {
      let cpuTimeEnd = process.cpuUsage();
      let stop_timestamp = Date.now();
      let stop = process.hrtime(begin);
      let output_file = tools.get_result_prefix(tools.LOGS_DIR, 'output', 'txt');
      fs.writeFileSync(output_file, JSON.stringify(res));
      let userTime = cpuTimeEnd.user - cpuTimeBegin.user;
      let sysTime = cpuTimeEnd.system - cpuTimeBegin.system;
      timedata[repetition] = [begin_timestamp, stop_timestamp, stop[0]*1e6 + stop[1]/1e3, userTime, sysTime];
      measurer(repetition + 1, finish);
    },
    (reason) => {
      console.log('Function invocation failed!');
      console.log(reason);
      process.exit(1);
    }
    );
  } else{
    finish();
  }
}
start = tools.start_benchmarking();
measurer(0,
  () => {
    end = tools.stop_benchmarking();
    let result = tools.get_result_prefix(tools.RESULTS_DIR, cfg.benchmark.name, 'csv')
    let csvWriter = createCsvWriter({
          path: result,
          header: ['Begin','End','Duration','User','Sys']
    });
    for(let i = 0; i < repetitions; ++i) {
      timedata[i][0] = strftime('%s.%L', new Date(timedata[i][0]));
      timedata[i][1] = strftime('%s.%L', new Date(timedata[i][1]));
    }
    let p = csvWriter.writeRecords(timedata);
    p.then( () => {
      let reduce_array = timedata.map( x => { x.pop(); return x} );
      experiment_data = {
        repetitions: repetitions,
        start: start,
        end: end,
        timestamps: reduce_array
      }
      console.log( JSON.stringify({experiment: experiment_data, runtime: tools.get_config()}, null, 2) )
    });
  }
);

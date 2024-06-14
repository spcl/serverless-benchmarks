const path = require('path'), fs = require('fs');

exports.handler = async function(context) {
    var body = JSON.stringify(context.request.body);
    var unbody = JSON.parse(body);
    var func = require('./function/function');
    var begin = Date.now()/1000;
    var start = process.hrtime();
    var ret = await func.handler(unbody);
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
        status: 200,
        body: JSON.stringify({
            begin,
            end,
            compute_time: micro,
            results_time: 0,
            result: ret,
            is_cold
        })
    };
};
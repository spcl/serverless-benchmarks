const {
  CloudEvent,
  HTTP
} = require('cloudevents');
const path = require('path');
const fs = require('fs');

async function handle(context, event) {
    
    const requestId = context.headers['x-request-id'] || context.headers['X-Request-ID'];


  // Ensure event data is parsed correctly
  const eventData = event ? event : context.body;
  context.log.info(`Received event: ${JSON.stringify(eventData)}`);

  const func = require('./function/function.js');
  const begin = Date.now() / 1000;
  const start = process.hrtime();

  try {
      // Call the handler function with the event data
      const ret = await func.handler(eventData);
      const elapsed = process.hrtime(start);
      const end = Date.now() / 1000;
      const micro = elapsed[1] / 1e3 + elapsed[0] * 1e6;

      let is_cold = false;
      const fname = path.join('/tmp', 'cold_run');
      if (!fs.existsSync(fname)) {
          is_cold = true;
          fs.closeSync(fs.openSync(fname, 'w'));
      }

      context.log.info(`Function result: ${JSON.stringify(ret)}`);

      return {
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: ret,
          request_id: requestId,
          is_cold: is_cold,
      };
  } catch (error) {
      context.log.error(`Error - invocation failed! Reason: ${error.message}`);
      return {
          begin: begin,
          end: Date.now() / 1000,
          compute_time: process.hrtime(start),
          results_time: 0,
          result: `Error - invocation failed! Reason: ${error.message}`,
          request_id: requestId,
          is_cold: false,
      };
  }
}

exports.handle = handle;

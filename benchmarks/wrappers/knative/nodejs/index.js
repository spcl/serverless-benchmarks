const { CloudEvent, HTTP } = require('cloudevents');
const handler = require('./function').handler;

async function handle(context, event) {
  const startTime = new Date();

  try {
    // Ensure event data is parsed correctly
    const eventData = event ? event : context.body;
    context.log.info(`Received event: ${JSON.stringify(eventData)}`);

    // Call the handler function with the event data
    const result = await handler(eventData);
    const endTime = new Date();

    context.log.info(`Function result: ${JSON.stringify(result)}`);
    const resultTime = (endTime - startTime) / 1000; // Time in seconds

    // Create a response
    const response = {
      begin: startTime.toISOString(),
      end: endTime.toISOString(),
      results_time: resultTime,
      result: result
    };

    // Return the response
    return {
      data: response,
      headers: { 'Content-Type': 'application/json' },
      statusCode: 200
    };
  } catch (error) {
    const endTime = new Date();
    const resultTime = (endTime - startTime) / 1000; // Time in seconds

    context.log.error(`Error - invocation failed! Reason: ${error.message}`);
    const response = {
      begin: startTime.toISOString(),
      end: endTime.toISOString(),
      results_time: resultTime,
      result: `Error - invocation failed! Reason: ${error.message}`
    };

    // Return the error response
    return {
      data: response,
      headers: { 'Content-Type': 'application/json' },
      statusCode: 500
    };
  }
}

module.exports = handle;

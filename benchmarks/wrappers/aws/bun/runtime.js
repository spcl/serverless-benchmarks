/**
 * Custom runtime while loop for AWS lambda.
 * Listens for function events, executes handler, and returns results.
 *
 * ENV variables based on https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-runtime
 * API endpoints based on https://docs.aws.amazon.com/lambda/latest/dg/runtimes-api.html
 */

import { handler } from "./handler.js";

const RUNTIME_API = process.env.AWS_LAMBDA_RUNTIME_API;
const API_BASE = `http://${RUNTIME_API}/2018-06-01/runtime`;

while (true) {
  const nextResponse = await fetch(`${API_BASE}/invocation/next`);
  const event = await nextResponse.json();
  const requestId = nextResponse.headers.get("Lambda-Runtime-Aws-Request-Id");

  // NOTE: If more context is needed inside the handler, they can be added here
  const context = { awsRequestId: requestId };

  try {
    const response = await handler(event, context);

    await fetch(`${API_BASE}/invocation/${requestId}/response`, {
      method: "POST",
      body: JSON.stringify(response),
    });
  } catch (error) {
    console.error(error);
    await fetch(`${API_BASE}/invocation/${requestId}/error`, {
      method: "POST",
      body: JSON.stringify({
        errorMessage: error.message,
        errorType: "Runtime.UserCodeError",
        stackTrace: error.stack ? error.stack.split("\n") : [],
      }),
    });
  }
}

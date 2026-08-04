"use strict";

const assert = require("node:assert/strict");
const { handler } = require("../benchmarks/000.microbenchmarks/010.sleep/nodejs/function.js");

(async () => {
  const sleep = 0.05;
  const started = process.hrtime.bigint();
  const output = await handler({ sleep });
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;

  assert.deepEqual(output, { result: sleep });
  assert.ok(elapsedMs >= 40, `handler returned after ${elapsedMs.toFixed(1)} ms`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

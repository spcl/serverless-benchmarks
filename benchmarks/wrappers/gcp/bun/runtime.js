/**
 * Custom server for GCP
 *
 * Based on https://docs.cloud.google.com/run/docs/container-contract
 */

import { handler } from "./handler.js";

const PORT = parseInt(process.env.PORT) || 8080;

Bun.serve({
  port: PORT,

  async fetch(req) {
    try {
      const mockRes = {
        status: function (code) {
          this.statusCode = code;
          return this;
        },
        json: function (data) {
          this.response = data;
          return this;
        },
      };
      // default nodejs handler expects req.body to be already parsed (like express.js)
      const mockReq = {
        body: await req.json(),
        headers: req.headers,
      };
      await handler(mockReq, mockRes);
      // cloud run functions do not have the function-execution-id header, set it explicitly to null (instead of undefined)
      mockRes.response.request_id = mockRes.response.request_id || null;
      return new Response(JSON.stringify(mockRes.response), {
        status: mockRes.statusCode || 200,
        headers: {
          "Content-Type": "application/json",
        },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
      });
    }
  },
});

console.log(`Listening on port ${PORT}`);

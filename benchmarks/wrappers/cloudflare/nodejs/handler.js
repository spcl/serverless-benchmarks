import { DurableObject } from "cloudflare:workers";

// Cloudflare Workers freezes Date.now() / performance.now() between I/O
// operations as a timing-sidechannel mitigation, so wall-clock time does
// not advance inside pure-compute sections. To record a meaningful
// compute_time, we issue a throwaway self-fetch that triggers I/O and
// unfreezes the clock before we sample it.
// Docs: https://developers.cloudflare.com/workers/reference/security-model/#step-1-disallow-timers-and-multi-threading
async function advanceWorkersClock(request) {
  try {
    const url = new URL(request.url);
    url.pathname = '/favicon';
    await fetch(url.toString(), { method: 'HEAD' });
  } catch (e) {
    // Ignore — we only care about the side effect of performing I/O.
  }
}

// Durable Object class for KV API compatibility
export class KVApiObject extends DurableObject {
  constructor(state, env) {
    super(state, env);
    this.storage = state.storage;
  }
  
  // Proxy methods to make the storage API accessible from the stub
  async put(key, value) {
    return await this.storage.put(key, value);
  }
  
  async get(key) {
    return await this.storage.get(key);
  }
  
  async delete(key) {
    return await this.storage.delete(key);
  }
  
  async list(options) {
    return await this.storage.list(options);
  }
}

export default {
  async fetch(request, env) {
    try {
      // Store R2 bucket binding and benchmark name in globals for fs-polyfill access
      if (env.R2) {
        globalThis.R2_BUCKET = env.R2;
      }
      if (env.BENCHMARK_NAME) {
        globalThis.BENCHMARK_NAME = env.BENCHMARK_NAME;
      }

      if (request.url.includes('favicon')) {
        return new Response('None');
      }

      // Get unique request ID from Cloudflare (CF-Ray header)
      const req_id = request.headers.get('CF-Ray') || crypto.randomUUID();

      // Start timing measurements
      const start = performance.now();
      const begin = Date.now() / 1000;


      // Parse JSON body first (similar to Azure handler which uses req.body)
      const req_text = await request.text();
      let event = {};
      if (req_text && req_text.length > 0) {
        try {
          event = JSON.parse(req_text);
        } catch (e) {
          // If body isn't JSON, keep event empty
          event = {};
        }
      }

      // Parse query string into event (URL parameters override/merge with body)
      // This makes it compatible with both input formats
      const urlParts = request.url.split('?');
      if (urlParts.length > 1) {
        const query = urlParts[1];
        const pairs = query.split('&');
        for (const p of pairs) {
          const [k, v] = p.split('=');
          try {
            if (v === undefined) {
              event[k] = null;
            } else if (!Number.isNaN(Number(v)) && Number.isFinite(Number(v))) {
              // mirror Python attempt to convert to int
              const n = Number(v);
              event[k] = Number.isInteger(n) ? parseInt(v, 10) : n;
            } else {
              event[k] = decodeURIComponent(v);
            }
          } catch (e) {
            event[k] = v;
          }
        }
      }

      // Set timestamps
      const income_timestamp = Math.floor(Date.now() / 1000);
      event['request-id'] = req_id;
      event['income-timestamp'] = income_timestamp;

      // Load the benchmark function module and initialize storage if available
      // With nodejs_compat enabled, we can use require() for CommonJS modules
      let funcModule;
      try {
        // Fallback to dynamic import for ES modules
        funcModule = await import('./function.js');
      } catch (e2) {
        throw new Error('Failed to import benchmark function module: ' + e2.message);
      }


      try {
        const storageModule = await import('./storage.js');
        if (storageModule && storageModule.storage && typeof storageModule.storage.init_instance === 'function') {
          storageModule.storage.init_instance({ env, request });
        } else {
          console.warn('storage module imported but storage.init_instance is missing; skipping storage setup');
        }
      } catch (e) {
        // storage module may not be bundled for benchmarks that don't need it
      }

      if (env.NOSQL_STORAGE_DATABASE) {
        try {
          const nosqlModule = await import('./nosql.js');
          if (nosqlModule && nosqlModule.nosql && typeof nosqlModule.nosql.init_instance === 'function') {
            nosqlModule.nosql.init_instance({ env, request });
          } else {
            console.warn('nosql module imported but nosql.init_instance is missing; skipping nosql setup');
          }
        } catch (e) {
          // nosql module might not exist for all benchmarks
          console.log('Could not initialize nosql:', e.message);
        }
      }

      // Execute the benchmark handler. Benchmarks expose `handler` either as a
      // named export (`exports.handler` / `export const handler`) or nested
      // under a default export (`export default { handler }`).
      let ret;
      try {
        const handler =
          (funcModule && typeof funcModule.handler === 'function' && funcModule.handler) ||
          (funcModule && funcModule.default && typeof funcModule.default.handler === 'function' && funcModule.default.handler);
        if (!handler) {
          throw new Error('benchmark handler function not found');
        }
        ret = await handler(event);
      } catch (err) {
        await advanceWorkersClock(request);
        // Calculate timing even for errors
        const end = Date.now() / 1000;
        const elapsed = performance.now() - start;
        const micro = elapsed * 1000; // Convert milliseconds to microseconds

        // Mirror Python behavior: return structured error payload
        const errorPayload = JSON.stringify({
          begin: begin,
          end: end,
          compute_time: micro,
          results_time: 0,
          result: { output: null },
          is_cold: false,
          is_cold_worker: false,
          container_id: '0',
          environ_container_id: 'no_id',
          request_id: '0',
          error: String(err && err.message ? err.message : err),
          stack: err && err.stack ? err.stack : undefined,
          event: event,
          env: env,
        });
        return new Response(errorPayload, { status: 500, headers: { 'Content-Type': 'application/json' } });
      }

      await advanceWorkersClock(request);

      // Now read the updated timer
      const end = Date.now() / 1000;
      const elapsed = performance.now() - start;
      const micro = elapsed * 1000; // Convert milliseconds to microseconds

      // Build log_data similar to Python handler
      const log_data = { output: ret && ret.result !== undefined ? ret.result : ret };
      if (ret && ret.measurement !== undefined) {
        log_data.measurement = ret.measurement;
      } else {
        log_data.measurement = {};
      }

      // Add memory usage to measurement
      const memUsage = process.memoryUsage();
      const memory_mb = memUsage.heapUsed / 1024 / 1024;
      log_data.measurement.memory_used_mb = memory_mb;

      if (event.logs !== undefined) {
        log_data.time = 0;
      }

      if (event.html) {
        return new Response(String(ret && ret.result !== undefined ? ret.result : ''), {
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        });
      }

      const responseBody = JSON.stringify({
        begin: begin,
        end: end,
        compute_time: micro,
        results_time: 0,
        result: log_data,
        is_cold: false,
        is_cold_worker: false,
        container_id: '0',
        environ_container_id: 'no_id',
        request_id: req_id,
      });

      return new Response(responseBody, { headers: { 'Content-Type': 'application/json' } });
    } catch (topLevelError) {
      // Catch any uncaught errors (module loading, syntax errors, etc.)
      // Try to include timing if available
      let errorBegin = 0;
      let errorEnd = 0;
      let errorMicro = 0;
      try {
        errorEnd = Date.now() / 1000;
        if (typeof begin !== 'undefined' && typeof start !== 'undefined') {
          errorBegin = begin;
          const elapsed = performance.now() - start;
          errorMicro = elapsed * 1000;
        }
      } catch (e) {
        // Ignore timing errors in error handler
      }
      
      const errorPayload = JSON.stringify({
        begin: errorBegin,
        end: errorEnd,
        compute_time: errorMicro,
        results_time: 0,
        result: { output: null },
        is_cold: false,
        is_cold_worker: false,
        container_id: '0',
        environ_container_id: 'no_id',
        request_id: '0',
        error: `Top-level error: ${topLevelError && topLevelError.message ? topLevelError.message : String(topLevelError)}`,
        stack: topLevelError && topLevelError.stack ? topLevelError.stack : undefined,
      });
      return new Response(errorPayload, { status: 500, headers: { 'Content-Type': 'application/json' } });
    }
  },
};

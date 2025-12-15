import { DurableObject } from "cloudflare:workers";

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

    // Initialize storage - try function module first, then fall back to wrapper storage
    try {
      if (funcModule && funcModule.storage && typeof funcModule.storage.init_instance === 'function') {
        funcModule.storage.init_instance({ env, request });
      } else {
        // Function doesn't export storage, so initialize wrapper storage directly
        try {
          const storageModule = await import('./storage.js');
          if (storageModule && storageModule.storage && typeof storageModule.storage.init_instance === 'function') {
            storageModule.storage.init_instance({ env, request });
          }
        } catch (storageErr) {
          // Ignore errors from storage initialization
        }
      }
    } catch (e) {
      // don't fail the request if storage init isn't available
    }

    // Initialize nosql if environment variable is set
    if (env.NOSQL_STORAGE_DATABASE) {
      try {
        const nosqlModule = await import('./nosql.js');
        if (nosqlModule && nosqlModule.nosql && typeof nosqlModule.nosql.init_instance === 'function') {
          nosqlModule.nosql.init_instance({ env, request });
        }
      } catch (e) {
        // nosql module might not exist for all benchmarks
        console.log('Could not initialize nosql:', e.message);
      }
    }

    // Execute the benchmark handler
    let ret;
    try {
      // Wrap the handler execution to handle sync-style async code
      // The benchmark code calls async nosql methods but doesn't await them
      // We need to serialize the execution
      if (funcModule && typeof funcModule.handler === 'function') {
        // Create a promise-aware execution context
        const handler = funcModule.handler;
        
        // Execute handler - it will return { result: [Promise, Promise, ...] }
        ret = await Promise.resolve(handler(event));
        
        // Deeply resolve all promises in the result
        if (ret && ret.result && Array.isArray(ret.result)) {
          ret.result = await Promise.all(ret.result.map(async item => await Promise.resolve(item)));
        }
      } else if (funcModule && funcModule.default && typeof funcModule.default.handler === 'function') {
        const handler = funcModule.default.handler;
        ret = await Promise.resolve(handler(event));
        
        if (ret && ret.result && Array.isArray(ret.result)) {
          ret.result = await Promise.all(ret.result.map(async item => await Promise.resolve(item)));
        }
      } else {
        throw new Error('benchmark handler function not found');
      }
    } catch (err) {
      // Trigger a fetch request to update the timer before measuring
      // Time measurements only update after a fetch request or R2 operation
      try {
        // Fetch the worker's own URL with favicon to minimize overhead
        const finalUrl = new URL(request.url);
        finalUrl.pathname = '/favicon';
        await fetch(finalUrl.toString(), { method: 'HEAD' });
      } catch (e) {
        // Ignore fetch errors
      }
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

        // Trigger a fetch request to update the timer before measuring
    // Time measurements only update after a fetch request or R2 operation
    try {
      // Fetch the worker's own URL with favicon to minimize overhead
      const finalUrl = new URL(request.url);
      finalUrl.pathname = '/favicon';
      await fetch(finalUrl.toString(), { method: 'HEAD' });
    } catch (e) {
      // Ignore fetch errors
    }
    
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


// Simple CommonJS polyfill for Cloudflare Workers
// This allows us to load CommonJS modules that use require() and module.exports
const moduleCache = {};

function createRequire(currentModule) {
  return function require(modulePath) {
    if (moduleCache[modulePath]) {
      return moduleCache[modulePath].exports;
    }
    
    // Create module object
    const module = { exports: {} };
    moduleCache[modulePath] = module;
    
    // This is a placeholder - actual module loading would happen here
    // For our use case, we'll manually register modules below
    throw new Error(`Module ${modulePath} not found in polyfill cache`);
  };
}

// Polyfill for __dirname and __filename if not available
if (typeof globalThis.__dirname === 'undefined') {
  globalThis.__dirname = '.';
}

if (typeof globalThis.__filename === 'undefined') {
  globalThis.__filename = './handler.js';
}

if (typeof globalThis.require === 'undefined') {
  globalThis.require = createRequire(globalThis);
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

      // Match behavior of the Python handler: parse body, parse URL params,
      // set request-id and income timestamp, call the benchmark function,
      // and return a JSON response with the same fields.

      if (request.url.includes('favicon')) {
        return new Response('None');
      }

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

    // Parse query string into event (simple parsing, mirrors Python logic)
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

    // Set request id and timestamps (Python used 0 for request id)
    const req_id = 0;
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

    // If the function module exposes a storage initializer, call it
    try {
      if (funcModule && funcModule.storage && typeof funcModule.storage.init_instance === 'function') {
        try {
          funcModule.storage.init_instance({ env, request });
        } catch (ignore) {}
      }
    } catch (e) {
      // don't fail the request if storage init isn't available
    }

    // Execute the benchmark handler
    let ret;
    try {
      if (funcModule && typeof funcModule.handler === 'function') {
        // handler may be sync or return a promise
        ret = await Promise.resolve(funcModule.handler(event));
      } else if (funcModule && funcModule.default && typeof funcModule.default.handler === 'function') {
        ret = await Promise.resolve(funcModule.default.handler(event));
      } else {
        throw new Error('benchmark handler function not found');
      }
    } catch (err) {
      // Mirror Python behavior: return structured error payload
      const errorPayload = JSON.stringify({
        begin: '0',
        end: '0',
        results_time: '0',
        result: { output: null },
        is_cold: false,
        is_cold_worker: false,
        container_id: '0',
        environ_container_id: 'no_id',
        request_id: '0',
        error: String(err && err.message ? err.message : err),
      });
      return new Response(errorPayload, { status: 500, headers: { 'Content-Type': 'application/json' } });
    }

    // Build log_data similar to Python handler
    const log_data = { output: ret && ret.result !== undefined ? ret.result : ret };
    if (ret && ret.measurement !== undefined) {
      log_data.measurement = ret.measurement;
    }
    if (event.logs !== undefined) {
      log_data.time = 0;
    }

    if (event.html) {
      return new Response(String(ret && ret.result !== undefined ? ret.result : ''), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    const responseBody = JSON.stringify({
      begin: '0',
      end: '0',
      results_time: '0',
      result: log_data,
      is_cold: false,
      is_cold_worker: false,
      container_id: '0',
      environ_container_id: 'no_id',
      request_id: '0',
    });

    return new Response(responseBody, { headers: { 'Content-Type': 'application/json' } });
    } catch (topLevelError) {
      // Catch any uncaught errors (module loading, syntax errors, etc.)
      const errorPayload = JSON.stringify({
        begin: '0',
        end: '0',
        results_time: '0',
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

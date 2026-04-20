// Container handler for Cloudflare Workers - Node.js
// This handler is used when deploying as a container worker

const http = require('http');
const crypto = require('crypto');
const Module = require('module');
const debug = require('util').debuglog('sebs');

// Monkey-patch the 'request' library to always include a User-Agent header
// This is needed because Wikimedia (and other sites) require a User-Agent
try {
  const originalRequire = Module.prototype.require;

  Module.prototype.require = function(id) {
    const module = originalRequire.apply(this, arguments);

    if (id === 'request') {
      // Wrap the request function to inject default headers
      const originalRequest = module;
      const wrappedRequest = function(options, callback) {
        if (typeof options === 'string') {
          options = { uri: options };
        }
        if (!options.headers) {
          options.headers = {};
        }
        if (!options.headers['User-Agent'] && !options.headers['user-agent']) {
          options.headers['User-Agent'] = 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2';
        }
        return originalRequest(options, callback);
      };
      // Copy all properties from original request
      Object.keys(originalRequest).forEach(key => {
        wrappedRequest[key] = originalRequest[key];
      });
      return wrappedRequest;
    }

    return module;
  };
} catch (e) {
  console.error('Failed to patch request module:', e);
}

// Import the benchmark function
const { handler: benchmarkHandler } = require('./function');

// Import storage and nosql if they exist
let storage, nosql;
try {
  storage = require('./storage');
} catch (e) {
  console.log('Storage module not available');
}
try {
  nosql = require('./nosql');
} catch (e) {
  console.log('NoSQL module not available');
}

const PORT = process.env.PORT || 8080;

const server = http.createServer(async (req, res) => {
  try {
    // Get unique request ID from Cloudflare (CF-Ray header)
    const reqId = req.headers['cf-ray'] || crypto.randomUUID();
    
    // Extract Worker URL from header for R2 and NoSQL proxy.
    //
    // Containers run in a separate runtime from Workers and cannot access R2 or
    // KV bindings directly — those bindings only exist in the Worker's `env`.
    // To let the benchmark code reach storage, worker.js injects its own public
    // origin into the X-Worker-URL header before forwarding the request here.
    // The container-side storage/nosql modules use this URL to call back into
    // the Worker over HTTP (e.g. POST ${workerUrl}/r2/upload), and worker.js
    // intercepts those paths (/r2/*, /nosql/*) and performs the binding call
    // on the container's behalf.
    const workerUrl = req.headers['x-worker-url'];
    if (workerUrl) {
      if (storage && storage.storage && storage.storage.set_worker_url) {
        storage.storage.set_worker_url(workerUrl);
      }
      if (nosql && nosql.nosql && nosql.nosql.set_worker_url) {
        nosql.nosql.set_worker_url(workerUrl);
      }
      console.log(`Set worker URL for R2/NoSQL proxy: ${workerUrl}`);
    }

    // Start timing measurements
    const begin = Date.now() / 1000;
    const start = performance.now();

    // Read request body
    let body = '';
    for await (const chunk of req) {
      body += chunk;
    }

    // Parse event from JSON body or URL params
    let event = {};
    if (body && body.length > 0) {
      try {
        event = JSON.parse(body);
      } catch (e) {
        console.error('Failed to parse JSON body:', e);
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON body', message: e.message }));
        return;
      }
    }

    // Parse URL parameters
    const url = new URL(req.url, `http://${req.headers.host}`);
    for (const [key, value] of url.searchParams) {
      if (!event[key]) {
        const intValue = parseInt(value);
        event[key] = isNaN(intValue) ? value : intValue;
      }
    }

    // Add request metadata
    const incomeTimestamp = Math.floor(Date.now() / 1000);
    event['request-id'] = reqId;
    event['income-timestamp'] = incomeTimestamp;

    // Call the benchmark function
    const ret = await benchmarkHandler(event);


    // Calculate elapsed time
    const end = Date.now() / 1000;
    const elapsed = performance.now() - start;
    const micro = elapsed * 1000; // Convert milliseconds to microseconds

    // Build log_data similar to native handler
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

    // Gated behind Node.js' built-in debuglog — enable with NODE_DEBUG=sebs
    debug('Sending response with log_data: %o', log_data);

    // Send response matching Python handler format exactly
    if (event.html) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(String(ret && ret.result !== undefined ? ret.result : ret));
    } else {
      const responseBody = JSON.stringify({
        begin: begin,
        end: end,
        results_time: 0,
        result: log_data,
        is_cold: false,
        is_cold_worker: false,
        container_id: '0',
        environ_container_id: 'no_id',
        request_id: reqId,
      });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(responseBody);
    }

  } catch (error) {
    console.error('Error processing request:', error);
    console.error('Stack trace:', error.stack);
    
    const errorPayload = JSON.stringify({
      error: error.message,
      stack: error.stack
    });
    
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(errorPayload);
  }
});

// Ensure server is listening before handling requests
server.listen(PORT, '0.0.0.0', () => {
  console.log(`Container server listening on 0.0.0.0:${PORT}`);
  console.log('Server ready to accept connections');
});

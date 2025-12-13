// Container handler for Cloudflare Workers - Node.js
// This handler is used when deploying as a container worker

const http = require('http');

// Monkey-patch the 'request' library to always include a User-Agent header
// This is needed because Wikimedia (and other sites) require a User-Agent
try {
  const Module = require('module');
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
  // Handle favicon requests
  if (req.url.includes('favicon')) {
    res.writeHead(200);
    res.end('None');
    return;
  }

  try {
    // Get unique request ID from Cloudflare (CF-Ray header)
    const crypto = require('crypto');
    const reqId = req.headers['cf-ray'] || crypto.randomUUID();
    
    // Extract Worker URL from header for R2 and NoSQL proxy
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

    console.error('!!! Event:', JSON.stringify(event));

    // For debugging: check /tmp directory before and after benchmark
    const fs = require('fs');
    console.error('!!! Files in /tmp before benchmark:', fs.readdirSync('/tmp'));

    // Call the benchmark function
    console.error('!!! Calling benchmark handler...');
    const ret = await benchmarkHandler(event);
    console.error('!!! Benchmark result:', JSON.stringify(ret));
    
    // Check what was downloaded
    console.error('!!! Files in /tmp after benchmark:', fs.readdirSync('/tmp'));
    const tmpFiles = fs.readdirSync('/tmp');
    for (const file of tmpFiles) {
      const filePath = `/tmp/${file}`;
      const stats = fs.statSync(filePath);
      console.error(`!!!   ${file}: ${stats.size} bytes`);
      if (stats.size < 500) {
        const content = fs.readFileSync(filePath, 'utf8');
        console.error(`!!!   First 300 chars: ${content.substring(0, 300)}`);
      }
    }

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

    console.log('Sending response with log_data:', log_data);

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

/**
 * Minimal request polyfill for Cloudflare Workers
 * Provides a subset of the 'request' npm package API using fetch()
 */

class RequestStream {
  constructor(url, options = {}) {
    this.url = url;
    this.options = options;
    this.pipeDestination = null;
  }

  pipe(destination) {
    this.pipeDestination = destination;
    
    // Start the fetch and pipe to destination
    (async () => {
      try {
        const response = await fetch(this.url, this.options);
        
        if (!response.ok) {
          this.pipeDestination.emit('error', new Error(`HTTP ${response.status}: ${response.statusText}`));
          return;
        }

        // Read the response body and write to destination
        const reader = response.body.getReader();
        
        while (true) {
          const { done, value } = await reader.read();
          
          if (done) {
            this.pipeDestination.end();
            break;
          }
          
          // Write chunk to destination stream
          if (!this.pipeDestination.write(value)) {
            // Backpressure - wait for drain
            await new Promise(resolve => {
              this.pipeDestination.once('drain', resolve);
            });
          }
        }
      } catch (error) {
        if (this.pipeDestination) {
          this.pipeDestination.emit('error', error);
        }
      }
    })();
    
    return this.pipeDestination;
  }
}

/**
 * Main request function - creates a request stream
 * @param {string|object} urlOrOptions - URL string or options object
 * @param {object} options - Additional options if first param is URL
 * @returns {RequestStream}
 */
function request(urlOrOptions, options) {
  let url, opts;
  
  if (typeof urlOrOptions === 'string') {
    url = urlOrOptions;
    opts = options || {};
  } else {
    url = urlOrOptions.url || urlOrOptions.uri;
    opts = urlOrOptions;
  }
  
  // Add default headers to avoid 403 errors from some servers
  const defaultHeaders = {
    'User-Agent': 'Mozilla/5.0 (compatible; Cloudflare-Workers/1.0)',
    'Accept': '*/*',
  };
  
  const headers = { ...defaultHeaders, ...(opts.headers || {}) };
  
  return new RequestStream(url, {
    method: opts.method || 'GET',
    headers: headers,
    body: opts.body,
  });
}

// Add common HTTP method shortcuts
request.get = (url, options) => request(url, { ...options, method: 'GET' });
request.post = (url, options) => request(url, { ...options, method: 'POST' });
request.put = (url, options) => request(url, { ...options, method: 'PUT' });
request.delete = (url, options) => request(url, { ...options, method: 'DELETE' });

// Export as CommonJS module
module.exports = request;
module.exports.default = request;

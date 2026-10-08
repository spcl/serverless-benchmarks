/**
 * Polyfill for the 'request' module using Cloudflare Workers fetch API
 * Implements the minimal interface needed for benchmark compatibility
 */

const { Writable } = require('node:stream');
const fs = require('node:fs');

function request(url, options, callback) {
  // Handle different call signatures
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  
  // Add default headers to mimic a browser request
  const fetchOptions = {
    ...options,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
      'Accept': '*/*',
      ...((options && options.headers) || {})
    }
  };
  
  // Create a simple object that has a pipe method
  const requestObj = {
    pipe(destination) {
      // Perform the fetch and write to destination
      fetch(url, fetchOptions)
        .then(async (response) => {
          if (!response.ok) {
            const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
            error.statusCode = response.status;
            destination.emit('error', error);
            if (callback) callback(error, response, null);
            return destination;
          }
          
          // Get the response as arrayBuffer and write it all at once
          const buffer = await response.arrayBuffer();
          
          // Write the buffer to the destination
          if (destination.write) {
            destination.write(Buffer.from(buffer));
            destination.end();
          }
          
          if (callback) callback(null, response, Buffer.from(buffer));
        })
        .catch((error) => {
          destination.emit('error', error);
          if (callback) callback(error, null, null);
        });
      
      return destination;
    },
    
    abort() {
      // No-op for compatibility
    }
  };
  
  return requestObj;
}

// Add common request methods
request.get = (url, options, callback) => {
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  return request(url, { ...options, method: 'GET' }, callback);
};

request.post = (url, options, callback) => {
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  return request(url, { ...options, method: 'POST' }, callback);
};

request.put = (url, options, callback) => {
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  return request(url, { ...options, method: 'PUT' }, callback);
};

request.delete = (url, options, callback) => {
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  return request(url, { ...options, method: 'DELETE' }, callback);
};

module.exports = request;

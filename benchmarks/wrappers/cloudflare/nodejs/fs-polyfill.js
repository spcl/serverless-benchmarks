import * as nodeFs from 'node:fs';
import { Writable } from 'node:stream';

/**
 * Read a file from R2 bucket
 * @param {string} path - File path in R2 bucket (e.g., 'templates/index.html')
 * @param {string|object|function} encoding - Encoding or options or callback
 * @param {function} callback - Callback function (err, data)
 */
export async function readFile(path, encoding, callback) {
  // Handle overloaded arguments: readFile(path, callback) or readFile(path, encoding, callback)
  let actualEncoding = 'utf8';
  let actualCallback = callback;
  
  if (typeof encoding === 'function') {
    actualCallback = encoding;
    actualEncoding = 'utf8';
  } else if (typeof encoding === 'string') {
    actualEncoding = encoding;
  } else if (typeof encoding === 'object' && encoding !== null && encoding.encoding) {
    actualEncoding = encoding.encoding;
  }

  try {
    // Check if R2 bucket is available
    if (!globalThis.R2_BUCKET) {
      throw new Error('R2 bucket not available. Ensure R2 binding is configured in wrangler.toml');
    }

    // Normalize path: remove leading './' or '/'
    let normalizedPath = path.replace(/^\.?\//, '');
    
    // Prepend benchmark name if available
    if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
      normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
    }
    
    // Get object from R2
    const object = await globalThis.R2_BUCKET.get(normalizedPath);
    
    if (!object) {
      throw new Error(`ENOENT: no such file or directory, open '${path}' (R2 key: ${normalizedPath})`);
    }

    // Read the content
    let content;
    if (actualEncoding === 'utf8' || actualEncoding === 'utf-8') {
      content = await object.text();
    } else if (actualEncoding === 'buffer' || actualEncoding === null) {
      content = await object.arrayBuffer();
    } else {
      // For other encodings, get text and let caller handle conversion
      content = await object.text();
    }

    if (actualCallback) {
      actualCallback(null, content);
    }
    return content;
  } catch (err) {
    if (actualCallback) {
      actualCallback(err, null);
    } else {
      throw err;
    }
  }
}

/**
 * Synchronous version of readFile (not truly sync in Workers, but returns a Promise)
 * Note: This is a compatibility shim - it still returns a Promise
 */
export function readFileSync(path, encoding) {
  return new Promise((resolve, reject) => {
    readFile(path, encoding || 'utf8', (err, data) => {
      if (err) reject(err);
      else resolve(data);
    });
  });
}

/**
 * Check if a file exists in R2
 */
export async function exists(path, callback) {
  try {
    if (!globalThis.R2_BUCKET) {
      if (callback) callback(false);
      return false;
    }

    let normalizedPath = path.replace(/^\.?\//, '');
    
    if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
      normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
    }
    
    const object = await globalThis.R2_BUCKET.head(normalizedPath);
    
    const result = object !== null;
    if (callback) callback(result);
    return result;
  } catch (err) {
    if (callback) callback(false);
    return false;
  }
}

/**
 * Get file stats from R2
 */
export async function stat(path, callback) {
  try {
    if (!globalThis.R2_BUCKET) {
      throw new Error('R2 bucket not available');
    }

    let normalizedPath = path.replace(/^\.?\//, '');
    
    if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
      normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
    }
    
    const object = await globalThis.R2_BUCKET.head(normalizedPath);
    
    if (!object) {
      throw new Error(`ENOENT: no such file or directory, stat '${path}'`);
    }

    const stats = {
      size: object.size,
      isFile: () => true,
      isDirectory: () => false,
      mtime: object.uploaded,
    };

    if (callback) callback(null, stats);
    return stats;
  } catch (err) {
    if (callback) callback(err, null);
    else throw err;
  }
}

/**
 * Create a write stream (memory-buffered, writes to R2 on close)
 */
export function createWriteStream(path, options) {
  const chunks = [];
  
  const stream = new Writable({
    write(chunk, encoding, callback) {
      chunks.push(chunk);
      callback();
    },
    final(callback) {
      // Write to R2 when stream is closed
      (async () => {
        try {
          if (!globalThis.R2_BUCKET) {
            throw new Error('R2 bucket not available');
          }

          let normalizedPath = path.replace(/^\.?\//, '');
          
          if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
            normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
          }
          
          const buffer = Buffer.concat(chunks);
          await globalThis.R2_BUCKET.put(normalizedPath, buffer);
          callback();
        } catch (err) {
          callback(err);
        }
      })();
    }
  });

  return stream;
}

/**
 * Write file to R2
 */
export async function writeFile(path, data, options, callback) {
  let actualCallback = callback;
  let actualOptions = options;
  
  if (typeof options === 'function') {
    actualCallback = options;
    actualOptions = {};
  }

  try {
    if (!globalThis.R2_BUCKET) {
      throw new Error('R2 bucket not available');
    }

    let normalizedPath = path.replace(/^\.?\//, '');
    
    if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
      normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
    }
    
    await globalThis.R2_BUCKET.put(normalizedPath, data);
    
    if (actualCallback) actualCallback(null);
  } catch (err) {
    if (actualCallback) actualCallback(err);
    else throw err;
  }
}

/**
 * Synchronous write file to R2
 */
export function writeFileSync(path, data, options) {
  return new Promise((resolve, reject) => {
    writeFile(path, data, options, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}

// Export everything from node:fs (what's available), but override specific methods
export default {
  ...nodeFs,
  readFile,
  readFileSync,
  exists,
  stat,
  createWriteStream,
  writeFile,
  writeFileSync,
};

// Also re-export all named exports from node:fs
export * from 'node:fs';
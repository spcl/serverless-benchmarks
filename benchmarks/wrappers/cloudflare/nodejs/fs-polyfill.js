import * as nodeFs from 'node:fs';
import { Writable } from 'node:stream';

// Global cache for files written/read during this request
// This allows sync operations to work within a single request context
if (!globalThis.FS_CACHE) {
  globalThis.FS_CACHE = new Map();
}

/**
 * Normalize a file path for R2
 */
function normalizePath(path) {
  let normalizedPath = path.replace(/^\.?\//, '').replace(/^tmp\//, '');
  
  if (globalThis.BENCHMARK_NAME && !normalizedPath.startsWith(globalThis.BENCHMARK_NAME + '/')) {
    normalizedPath = globalThis.BENCHMARK_NAME + '/' + normalizedPath;
  }
  
  return normalizedPath;
}

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

    const normalizedPath = normalizePath(path);
    
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
      const arrayBuffer = await object.arrayBuffer();
      content = Buffer.from(arrayBuffer);
    } else {
      // For other encodings, get text and let caller handle conversion
      content = await object.text();
    }
    
    // Store in cache for potential synchronous access
    if (globalThis.FS_CACHE) {
      globalThis.FS_CACHE.set(normalizedPath, content);
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
 * Synchronous version of readFile
 * Reads from cache if available, otherwise throws error
 */
export function readFileSync(path, encoding) {
  const normalizedPath = normalizePath(path);
  
  // Check cache first
  if (globalThis.FS_CACHE && globalThis.FS_CACHE.has(normalizedPath)) {
    const data = globalThis.FS_CACHE.get(normalizedPath);
    
    if (encoding === 'utf8' || encoding === 'utf-8') {
      return typeof data === 'string' ? data : Buffer.from(data).toString('utf8');
    } else if (encoding === null || encoding === 'buffer') {
      return Buffer.isBuffer(data) ? data : Buffer.from(data);
    }
    return data;
  }
  
  // File not in cache - in Workers we can't do sync I/O
  throw new Error(`ENOENT: no such file or directory, open '${path}'. File not in cache. In Cloudflare Workers, files must be written in the same request before being read synchronously.`);
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
 * Synchronous version of exists
 * Checks cache for file existence
 */
export function existsSync(path) {
  if (!globalThis.R2_BUCKET) {
    return false;
  }

  const normalizedPath = normalizePath(path);
  
  // Check if file is in cache
  if (globalThis.FS_CACHE && globalThis.FS_CACHE.has(normalizedPath)) {
    return true;
  }
  
  // File not in cache
  return false;
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

          const normalizedPath = normalizePath(path);
          
          const buffer = Buffer.concat(chunks);
          
          // Store in cache for synchronous access
          if (globalThis.FS_CACHE) {
            globalThis.FS_CACHE.set(normalizedPath, buffer);
          }
          
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
  existsSync,
  stat,
  createWriteStream,
  writeFile,
  writeFileSync,
};

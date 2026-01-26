const fs = require('fs');
const path = require('path');
const uuid = require('uuid');

/**
 * Storage module for Cloudflare Node.js Containers
 * Uses HTTP proxy to access R2 storage through the Worker's R2 binding
 */

class storage {
  constructor() {
    this.r2_enabled = true;
  }
  
  static worker_url = null; // Set by handler from X-Worker-URL header

  
  static worker_url = null; // Set by handler from X-Worker-URL header

  static unique_name(name) {
    const parsed = path.parse(name);
    const uuid_name = uuid.v4().split('-')[0];
    return path.join(parsed.dir, `${parsed.name}.${uuid_name}${parsed.ext}`);
  }

  static init_instance(entry) {
    if (!storage.instance) {
      storage.instance = new storage();
    }
    return storage.instance;
  }
  
  static set_worker_url(url) {
    storage.worker_url = url;
  }
  
  static get_instance() {
    if (!storage.instance) {
      storage.init_instance();
    }
    return storage.instance;
  }

  async upload_stream(bucket, key, data) {
    if (!this.r2_enabled) {
      console.log('Warning: R2 not configured, skipping upload');
      return key;
    }

    if (!storage.worker_url) {
      throw new Error('Worker URL not set - cannot access R2');
    }

    const unique_key = storage.unique_name(key);

    // Convert data to Buffer if needed
    let buffer;
    if (Buffer.isBuffer(data)) {
      buffer = data;
    } else if (typeof data === 'string') {
      buffer = Buffer.from(data, 'utf-8');
    } else if (data instanceof ArrayBuffer) {
      buffer = Buffer.from(data);
    } else {
      buffer = Buffer.from(String(data), 'utf-8');
    }

    // Upload via worker proxy
    const params = new URLSearchParams({ bucket, key: unique_key });
    const url = `${storage.worker_url}/r2/upload?${params}`;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: buffer,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      const result = await response.json();
      return result.key;
    } catch (error) {
      console.error('R2 upload error:', error);
      throw new Error(`Failed to upload to R2: ${error.message}`);
    }
  }

  async download_stream(bucket, key) {
    if (!this.r2_enabled) {
      throw new Error('R2 not configured');
    }

    if (!storage.worker_url) {
      throw new Error('Worker URL not set - cannot access R2');
    }

    // Download via worker proxy
    const params = new URLSearchParams({ bucket, key });
    const url = `${storage.worker_url}/r2/download?${params}`;

    try {
      const response = await fetch(url);

      if (response.status === 404) {
        throw new Error(`Object not found: ${key}`);
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      const arrayBuffer = await response.arrayBuffer();
      return Buffer.from(arrayBuffer);
    } catch (error) {
      console.error('R2 download error:', error);
      throw new Error(`Failed to download from R2: ${error.message}`);
    }
  }

  upload(bucket, key, filepath) {
    // Generate unique key synchronously so it can be returned immediately
    const unique_key = storage.unique_name(key);

    // Read file from disk and upload
    if (fs.existsSync(filepath)) {
      const data = fs.readFileSync(filepath);
      // Call internal version that doesn't generate another unique key
      const uploadPromise = this._upload_stream_with_key(bucket, unique_key, data);
      return [unique_key, uploadPromise];
    }

    console.error(`!!! [storage.upload] File not found: ${filepath}`);
    throw new Error(`upload(): file not found: ${filepath}`);
  }

  async _upload_stream_with_key(bucket, key, data) {
    // Internal method that uploads with exact key (no unique naming)
    console.log(`[storage._upload_stream_with_key] Starting upload: bucket=${bucket}, key=${key}, data_size=${data.length}`);
    
    if (!this.r2_enabled) {
      console.log('Warning: R2 not configured, skipping upload');
      return key;
    }

    if (!storage.worker_url) {
      console.error('[storage._upload_stream_with_key] Worker URL not set!');
      throw new Error('Worker URL not set - cannot access R2');
    }
    
    console.log(`[storage._upload_stream_with_key] Worker URL: ${storage.worker_url}`);

    // Convert data to Buffer if needed
    let buffer;
    if (Buffer.isBuffer(data)) {
      buffer = data;
    } else if (typeof data === 'string') {
      buffer = Buffer.from(data, 'utf-8');
    } else if (data instanceof ArrayBuffer) {
      buffer = Buffer.from(data);
    } else {
      buffer = Buffer.from(String(data), 'utf-8');
    }

    // Upload via worker proxy
    const params = new URLSearchParams({ bucket, key });
    const url = `${storage.worker_url}/r2/upload?${params}`;
    console.log(`[storage._upload_stream_with_key] Uploading to URL: ${url}, buffer size: ${buffer.length}`);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: buffer,
      });
      
      console.log(`[storage._upload_stream_with_key] Response status: ${response.status}`);

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`[storage._upload_stream_with_key] Upload failed: ${response.status} - ${errorText}`);
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      const result = await response.json();
      console.log(`[storage._upload_stream_with_key] Upload successful, returned key: ${result.key}`);
      return result.key;
    } catch (error) {
      console.error('R2 upload error:', error);
      throw new Error(`Failed to upload to R2: ${error.message}`);
    }
  }

  async download(bucket, key, filepath) {
    const data = await this.download_stream(bucket, key);

    let real_fp = filepath;
    if (!filepath.startsWith('/tmp')) {
      real_fp = path.join('/tmp', path.resolve(filepath));
    }

    // Write data to file
    fs.mkdirSync(path.dirname(real_fp), { recursive: true });
    fs.writeFileSync(real_fp, data);
  }

  async download_directory(bucket, prefix, out_path) {
    // List all objects with the prefix and download each one
    if (!this.r2_enabled) {
      console.log('Warning: R2 not configured, skipping download_directory');
      return;
    }

    if (!storage.worker_url) {
      throw new Error('Worker URL not set - cannot access R2');
    }

    // List objects via worker proxy
    const listParams = new URLSearchParams({ bucket, prefix });
    const listUrl = `${storage.worker_url}/r2/list?${listParams}`;
    
    try {
      const response = await fetch(listUrl, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      const result = await response.json();
      const objects = result.objects || [];
      
      for (const obj of objects) {
        const file_name = obj.key;
        const path_to_file = path.dirname(file_name);
        fs.mkdirSync(path.join(out_path, path_to_file), { recursive: true });
        await this.download(bucket, file_name, path.join(out_path, file_name));
      }
    } catch (error) {
      console.error('R2 download_directory error:', error);
      throw new Error(`Failed to download directory from R2: ${error.message}`);
    }
  }

  uploadStream(bucket, key) {
    // Return [stream, promise, unique_key] to match native wrapper API
    const unique_key = storage.unique_name(key);
    
    const stream = require('stream');
    const passThrough = new stream.PassThrough();
    const chunks = [];
    
    passThrough.on('data', (chunk) => chunks.push(chunk));
    
    const upload = new Promise((resolve, reject) => {
      passThrough.on('end', async () => {
        try {
          const buffer = Buffer.concat(chunks);
          await this._upload_stream_with_key(bucket, unique_key, buffer);
          resolve();
        } catch (err) {
          reject(err);
        }
      });
      passThrough.on('error', reject);
    });
    
    return [passThrough, upload, unique_key];
  }

  async downloadStream(bucket, key) {
    // Return a Promise that resolves to a readable stream
    const data = await this.download_stream(bucket, key);
    const stream = require('stream');
    const readable = new stream.Readable();
    readable.push(data);
    readable.push(null); // Signal end of stream
    return readable;
  }
}

module.exports.storage = storage;

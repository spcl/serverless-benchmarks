const fs = require('fs');
const path = require('path');
const uuid = require('uuid');

const MULTIPART_THRESHOLD = 10 * 1024 * 1024;
const PART_SIZE = 10 * 1024 * 1024;

function isRetryableSingleUploadError(error) {
  const message = error?.message || '';
  return /HTTP 4(?:08|13|29)|request body|payload|too large|content length|body size|stream/i.test(message);
}

/**
 * Storage module for Cloudflare Node.js Containers
 * Uses HTTP proxy to access R2 storage through the Worker's R2 binding
 */

class storage {
  constructor() {
    this.r2_enabled = true;
  }
  
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

  _toBuffer(data) {
    if (Buffer.isBuffer(data)) {
      return data;
    }
    if (typeof data === 'string') {
      return Buffer.from(data, 'utf-8');
    }
    if (data instanceof ArrayBuffer) {
      return Buffer.from(data);
    }
    return Buffer.from(String(data), 'utf-8');
  }

  async _postJson(url, body = Buffer.alloc(0), contentType = null) {
    const options = {
      method: 'POST',
      body,
    };

    if (contentType) {
      options.headers = { 'Content-Type': contentType };
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    return response.json();
  }

  async _single_upload(key, buffer) {
    const params = new URLSearchParams({ key });
    const url = `${storage.worker_url}/r2/upload?${params}`;
    const result = await this._postJson(url, buffer);
    return result.key;
  }

  async _multipart_upload(key, buffer) {
    const initParams = new URLSearchParams({ key });
    const initUrl = `${storage.worker_url}/r2/multipart-init?${initParams}`;
    const init = await this._postJson(initUrl);
    const uploadId = init.uploadId;
    const uploadKey = init.key;
    const completedParts = [];

    for (let offset = 0, partNumber = 1; offset < buffer.length; offset += PART_SIZE, partNumber += 1) {
      const chunk = buffer.subarray(offset, offset + PART_SIZE);
      const partParams = new URLSearchParams({
        key: uploadKey,
        uploadId,
        partNumber: String(partNumber),
      });
      const partUrl = `${storage.worker_url}/r2/multipart-part?${partParams}`;
      const part = await this._postJson(partUrl, chunk, 'application/octet-stream');
      completedParts.push({ partNumber: part.partNumber, etag: part.etag });
    }

    const completeParams = new URLSearchParams({ key: uploadKey, uploadId });
    const completeUrl = `${storage.worker_url}/r2/multipart-complete?${completeParams}`;
    const result = await this._postJson(
      completeUrl,
      Buffer.from(JSON.stringify({ parts: completedParts }), 'utf-8'),
      'application/json'
    );
    return result.key;
  }

  async _upload_bytes(key, buffer) {
    if (buffer.length > MULTIPART_THRESHOLD) {
      return this._multipart_upload(key, buffer);
    }

    try {
      return await this._single_upload(key, buffer);
    } catch (error) {
      if (!isRetryableSingleUploadError(error)) {
        throw error;
      }

      console.warn(
        `[storage] single upload failed for ${key}; retrying with multipart upload: ${error.message}`
      );
      return this._multipart_upload(key, buffer);
    }
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
    const buffer = this._toBuffer(data);

    try {
      return await this._upload_bytes(unique_key, buffer);
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

    const buffer = this._toBuffer(data);
    console.log(`[storage._upload_stream_with_key] Uploading key=${key}, buffer size: ${buffer.length}`);

    try {
      const resultKey = await this._upload_bytes(key, buffer);
      console.log(`[storage._upload_stream_with_key] Upload successful, returned key: ${resultKey}`);
      return resultKey;
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

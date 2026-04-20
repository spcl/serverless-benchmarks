const fs = require('fs');
const path = require('path');
const uuid = require('uuid');
const debug = require('util').debuglog('sebs');

// Cloudflare Workers enforce a 100 MB request body limit at the edge.
// Use multipart upload for payloads larger than this threshold so that
// each individual request stays well below that limit. R2 requires parts
// of at least 5 MB.
const MULTIPART_THRESHOLD = 10 * 1024 * 1024;
const PART_SIZE = 10 * 1024 * 1024;

function isRetryableSingleUploadError(error) {
  const message = error?.message || '';
  return /HTTP 4(?:08|13|29)|request body|payload|too large|content length|body size|stream/i.test(message);
}

/**
 * Storage module for Cloudflare Node.js Containers.
 *
 * On Cloudflare, object storage (R2) is normally accessed through a Worker
 * binding (`env.R2_BUCKET`). That binding only exists inside the Worker
 * runtime, so a container cannot talk to R2 directly the way a Lambda or
 * Cloud Function talks to S3/GCS with a regular SDK. Instead, the container
 * forwards each storage operation over HTTP to the parent Worker (see
 * worker.js), which holds the R2 binding and performs the actual
 * get/put/list/multipart calls.
 *
 * R2 does expose an S3-compatible HTTPS API that a container could call
 * without a Worker proxy, but that path requires provisioning and injecting
 * R2 access keys into the container and diverges from how the Worker-based
 * benchmarks access R2. Routing through the Worker keeps a single code path
 * and credential model for both deployment types.
 *
 * Because of this, the HTTP endpoint depends on the Worker's URL, which is
 * not known ahead of time. The handler receives it via the X-Worker-URL
 * header on the incoming request and installs it here through
 * set_worker_url() before any storage call is made.
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

      debug(
        '[storage] single upload failed for %s; retrying with multipart upload: %s',
        key,
        error.message
      );
      return this._multipart_upload(key, buffer);
    }
  }

  async upload_stream(bucket, key, data) {
    if (!this.r2_enabled) {
      debug('R2 not configured, skipping upload');
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
      debug('R2 upload error: %o', error);
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
      debug('R2 download error: %o', error);
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

    debug('[storage.upload] File not found: %s', filepath);
    throw new Error(`upload(): file not found: ${filepath}`);
  }

  async _upload_stream_with_key(bucket, key, data) {
    debug(
      '[storage._upload_stream_with_key] Starting upload: bucket=%s, key=%s, data_size=%d',
      bucket,
      key,
      data.length
    );

    if (!this.r2_enabled) {
      debug('R2 not configured, skipping upload');
      return key;
    }

    if (!storage.worker_url) {
      throw new Error('Worker URL not set - cannot access R2');
    }

    debug('[storage._upload_stream_with_key] Worker URL: %s', storage.worker_url);

    const buffer = this._toBuffer(data);
    debug('[storage._upload_stream_with_key] Uploading key=%s, buffer size: %d', key, buffer.length);

    try {
      const resultKey = await this._upload_bytes(key, buffer);
      debug('[storage._upload_stream_with_key] Upload successful, returned key: %s', resultKey);
      return resultKey;
    } catch (error) {
      debug('R2 upload error: %o', error);
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
    if (!this.r2_enabled) {
      debug('R2 not configured, skipping download_directory');
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
      debug('R2 download_directory error: %o', error);
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

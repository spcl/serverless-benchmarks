const fs = require('fs');
const path = require('path');
const uuid = require('uuid');

// Storage wrapper compatible with the Python storage implementation.
// Supports Cloudflare R2 (via env.R2) when available; falls back to
// filesystem-based operations when running in Node.js (for local tests).

class storage {
  constructor() {
    this.handle = null; // R2 binding
    this.written_files = new Set();
  }

  static unique_name(name) {
    const parsed = path.parse(name);
    const uuid_name = uuid.v4().split('-')[0];
    return path.join(parsed.dir, `${parsed.name}.${uuid_name}${parsed.ext}`);
  }

  // entry is expected to be an object with `env` (Workers) or nothing for Node
  static init_instance(entry) {
    storage.instance = new storage();
    if (entry && entry.env && entry.env.R2) {
      storage.instance.handle = entry.env.R2;
    }
    storage.instance.written_files = new Set();
  }

  // Upload a file given a local filepath. In Workers env this is not available
  // so callers should use upload_stream or pass raw data. For Node.js we read
  // the file from disk and put it into R2 if available, otherwise throw.
  async upload(__bucket, key, filepath) {
    // If file was previously written during this invocation, use /tmp absolute
    let realPath = filepath;
    if (this.written_files.has(filepath)) {
      realPath = path.join('/tmp', path.resolve(filepath));
    }

    // Read file content
    if (fs && fs.existsSync(realPath)) {
      const data = fs.readFileSync(realPath);
      return await this.upload_stream(__bucket, key, data);
    }

    // If running in Workers (no fs) and caller provided Buffer/Stream, they
    // should call upload_stream directly. Otherwise, throw.
    throw new Error('upload(): file not found on disk and no R2 handle provided');
  }

  async download(__bucket, key, filepath) {
    const data = await this.download_stream(__bucket, key);

    let real_fp = filepath;
    if (!filepath.startsWith('/tmp')) {
      real_fp = path.join('/tmp', path.resolve(filepath));
    }

    this.written_files.add(filepath);

    // Write data to file if we have fs
    if (fs) {
      fs.mkdirSync(path.dirname(real_fp), { recursive: true });
      if (Buffer.isBuffer(data)) {
        fs.writeFileSync(real_fp, data);
      } else {
        fs.writeFileSync(real_fp, Buffer.from(String(data)));
      }
      return;
    }

    // In Workers environment, callers should use stream APIs directly.
    return;
  }

  async download_directory(__bucket, prefix, out_path) {
    if (!this.handle) {
      throw new Error('download_directory requires R2 binding (env.R2)');
    }

    const list_res = await this.handle.list({ prefix });
    const objects = list_res.objects || [];
    for (const obj of objects) {
      const file_name = obj.key;
      const path_to_file = path.dirname(file_name);
      fs.mkdirSync(path.join(out_path, path_to_file), { recursive: true });
      await this.download(__bucket, file_name, path.join(out_path, file_name));
    }
  }

  async upload_stream(__bucket, key, data) {
    const unique_key = storage.unique_name(key);
    if (this.handle) {
      // R2 put accepts ArrayBuffer, ReadableStream, or string
      await this.handle.put(unique_key, data);
      return unique_key;
    }

    // If no R2, write to local fs as fallback
    if (fs) {
      const outPath = path.join('/tmp', unique_key);
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      if (Buffer.isBuffer(data)) fs.writeFileSync(outPath, data);
      else fs.writeFileSync(outPath, Buffer.from(String(data)));
      return unique_key;
    }

    throw new Error('upload_stream(): no storage backend available');
  }

  async download_stream(__bucket, key) {
    if (this.handle) {
      const obj = await this.handle.get(key);
      if (!obj) return null;
      // R2 object provides arrayBuffer()/text() helpers in Workers
      if (typeof obj.arrayBuffer === 'function') {
        const ab = await obj.arrayBuffer();
        return Buffer.from(ab);
      }
      if (typeof obj.text === 'function') {
        return await obj.text();
      }
      // Fallback: return null
      return null;
    }

    // Fallback to local filesystem
    const localPath = path.join('/tmp', key);
    if (fs && fs.existsSync(localPath)) {
      return fs.readFileSync(localPath);
    }

    throw new Error('download_stream(): object not found');
  }

  static get_instance() {
    if (!storage.instance) {
      throw new Error('must init storage singleton first');
    }
    return storage.instance;
  }
}

module.exports.storage = storage;

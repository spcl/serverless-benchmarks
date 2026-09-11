// NoSQL wrapper for Cloudflare Workers
// Uses KV namespaces for storage
// Returns Promises that the handler will resolve

class nosql {
  constructor() {
    this.env = null;
  }

  static init_instance(entry) {
    // Reuse existing instance if it exists, otherwise create new one
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }

    if (entry && entry.env) {
      nosql.instance.env = entry.env;
      // Share env globally so bundled copies of this module (inlined by esbuild
      // into function.js) can also reach the live KV bindings.
      globalThis._nosqlEnv = entry.env;
    }
  }

  _get_table(tableName) {
    // Fall back to the global env bridge for copies of this class that were
    // inlined by esbuild into a separate bundle (e.g. function.js) and
    // therefore have a different static `instance` from the one initialized
    // by handler.js via `import('./nosql.js')`.
    const env = this.env || globalThis._nosqlEnv;
    if (!env) {
      throw new Error(`nosql env not initialized for table ${tableName}`);
    }

    // Unlike AWS/Azure/GCP where you instantiate a client SDK and address
    // resources by name, Cloudflare Workers expose every bound resource
    // (KV namespace, R2 bucket, D1 database, queue, etc.) as a property on
    // the `env` object passed into the fetch handler. The property name is
    // the binding name declared in wrangler.toml, so looking up a KV
    // namespace by its table name is simply `env[tableName]`.
    const table = env[tableName];
    if (!table || typeof table.get !== 'function' || typeof table.put !== 'function') {
      const envKeys = Object.keys(env || {});
      throw new Error(
        `KV binding '${tableName}' not found. env keys: [${envKeys.join(', ')}]`
      );
    }

    return table;
  }

  _key(primaryKey, secondaryKey) {
    return `${primaryKey[1]}#${secondaryKey[1]}`;
  }

  _indexKey(primaryKey) {
    return `__sebs_idx__${primaryKey[1]}`;
  }

  async _readIndex(table, primaryKey) {
    const raw = await table.get(this._indexKey(primaryKey));
    if (raw === null) {
      return [];
    }
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  async _writeIndex(table, primaryKey, values) {
    await table.put(this._indexKey(primaryKey), JSON.stringify(values));
  }

  // Async methods - build.js will patch function.js to await these
  async insert(tableName, primaryKey, secondaryKey, data) {
    const keyData = { ...data };
    keyData[primaryKey[0]] = primaryKey[1];
    keyData[secondaryKey[0]] = secondaryKey[1];

    const table = this._get_table(tableName);
    await table.put(this._key(primaryKey, secondaryKey), JSON.stringify(keyData));

    const index = await this._readIndex(table, primaryKey);
    if (!index.includes(secondaryKey[1])) {
      index.push(secondaryKey[1]);
      await this._writeIndex(table, primaryKey, index);
    }
  }

  async get(tableName, primaryKey, secondaryKey) {
    const table = this._get_table(tableName);
    const raw = await table.get(this._key(primaryKey, secondaryKey));
    if (raw === null) {
      return null;
    }

    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }

  async update(tableName, primaryKey, secondaryKey, updates) {
    const existing = await this.get(tableName, primaryKey, secondaryKey) || {};
    const merged = { ...existing, ...updates };
    await this.insert(tableName, primaryKey, secondaryKey, merged);
  }

  async query(tableName, primaryKey, secondaryKeyName) {
    const table = this._get_table(tableName);
    let secondaryKeys = await this._readIndex(table, primaryKey);

    // Fallback for legacy namespaces without explicit index key.
    if (secondaryKeys.length === 0) {
      const listed = await table.list({ prefix: `${primaryKey[1]}#` });
      secondaryKeys = (listed.keys || []).map((k) => k.name.split('#').slice(1).join('#'));
    }

    const results = [];

    for (const secondaryValue of secondaryKeys) {
      const raw = await table.get(`${primaryKey[1]}#${secondaryValue}`);
      if (raw === null) {
        continue;
      }
      try {
        results.push(JSON.parse(raw));
      } catch {
        results.push(raw);
      }
    }

    return results;
  }

  async delete(tableName, primaryKey, secondaryKey) {
    const table = this._get_table(tableName);
    await table.delete(this._key(primaryKey, secondaryKey));

    const index = await this._readIndex(table, primaryKey);
    const next = index.filter((v) => v !== secondaryKey[1]);
    if (next.length !== index.length) {
      await this._writeIndex(table, primaryKey, next);
    }
  }

  static get_instance() {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
}

export { nosql };

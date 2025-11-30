// NoSQL wrapper for Cloudflare Workers
// Uses Durable Objects for storage
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
    }
  }

  _get_table(tableName) {
    // Don't cache stubs - they are request-scoped and cannot be reused
    // Always create a fresh stub for each request
    if (!this.env) {
      throw new Error(`nosql env not initialized for table ${tableName}`);
    }
    
    if (!this.env.DURABLE_STORE) {
      // Debug: log what we have
      const envKeys = Object.keys(this.env || {});
      const durableStoreType = typeof this.env.DURABLE_STORE;
      throw new Error(
        `DURABLE_STORE binding not found. env keys: [${envKeys.join(', ')}], DURABLE_STORE type: ${durableStoreType}`
      );
    }
    
    // Get a Durable Object ID based on the table name and create a fresh stub
    const id = this.env.DURABLE_STORE.idFromName(tableName);
    return this.env.DURABLE_STORE.get(id);
  }

  // Async methods - build.js will patch function.js to await these
  async insert(tableName, primaryKey, secondaryKey, data) {
    const keyData = { ...data };
    keyData[primaryKey[0]] = primaryKey[1];
    keyData[secondaryKey[0]] = secondaryKey[1];

    const durableObjStub = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;
    
    await durableObjStub.put(compositeKey, keyData);
  }

  async get(tableName, primaryKey, secondaryKey) {
    const durableObjStub = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;

    const result = await durableObjStub.get(compositeKey);
    return result || null;
  }

  async update(tableName, primaryKey, secondaryKey, updates) {
    const existing = await this.get(tableName, primaryKey, secondaryKey) || {};
    const merged = { ...existing, ...updates };
    await this.insert(tableName, primaryKey, secondaryKey, merged);
  }

  async query(tableName, primaryKey, secondaryKeyName) {
    const durableObjStub = this._get_table(tableName);
    const prefix = `${primaryKey[1]}#`;
    
    // List all keys with the prefix
    const allEntries = await durableObjStub.list({ prefix });
    const results = [];
    
    for (const [key, value] of allEntries) {
      results.push(value);
    }
    
    return results;
  }

  async delete(tableName, primaryKey, secondaryKey) {
    const durableObjStub = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;

    await durableObjStub.delete(compositeKey);
  }

  static get_instance() {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
}

export { nosql };

// NoSQL wrapper for Cloudflare Workers
// Supports Cloudflare KV or Durable Objects when available

class nosql {
  constructor() {
    this.handle = null; // KV or Durable Object binding
    this._tables = {};
  }

  static init_instance(entry) {
    nosql.instance = new nosql();
    if (entry && entry.env) {
      nosql.instance.env = entry.env;
    }
  }

  _get_table(tableName) {
    if (!(tableName in this._tables)) {
      const envName = `NOSQL_STORAGE_TABLE_${tableName}`;
      
      if (this.env && this.env[envName]) {
        this._tables[tableName] = this.env[envName];
      } else if (this.env && this.env[tableName]) {
        // Try direct table name
        this._tables[tableName] = this.env[tableName];
      } else {
        throw new Error(
          `Couldn't find an environment variable ${envName} for table ${tableName}`
        );
      }
    }

    return this._tables[tableName];
  }

  async insert(tableName, primaryKey, secondaryKey, data) {
    const keyData = { ...data };
    keyData[primaryKey[0]] = primaryKey[1];
    keyData[secondaryKey[0]] = secondaryKey[1];

    const table = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;
    
    // For KV binding
    if (table && typeof table.put === 'function') {
      await table.put(compositeKey, JSON.stringify(keyData));
    } else {
      throw new Error('NoSQL table binding not properly configured');
    }
  }

  async get(tableName, primaryKey, secondaryKey) {
    const table = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;

    if (table && typeof table.get === 'function') {
      const result = await table.get(compositeKey);
      if (result) {
        return JSON.parse(result);
      }
      return null;
    }
    
    throw new Error('NoSQL table binding not properly configured');
  }

  async update(tableName, primaryKey, secondaryKey, updates) {
    // For simple KV, update is same as put with merged data
    const existing = await this.get(tableName, primaryKey, secondaryKey) || {};
    const merged = { ...existing, ...updates };
    await this.insert(tableName, primaryKey, secondaryKey, merged);
  }

  async query(tableName, primaryKey, secondaryKeyName) {
    const table = this._get_table(tableName);
    const prefix = `${primaryKey[1]}#`;
    
    if (table && typeof table.list === 'function') {
      const list = await table.list({ prefix });
      const results = [];
      
      for (const key of list.keys) {
        const value = await table.get(key.name);
        if (value) {
          results.push(JSON.parse(value));
        }
      }
      
      return results;
    }
    
    throw new Error('NoSQL table binding not properly configured');
  }

  async delete(tableName, primaryKey, secondaryKey) {
    const table = this._get_table(tableName);
    const compositeKey = `${primaryKey[1]}#${secondaryKey[1]}`;

    if (table && typeof table.delete === 'function') {
      await table.delete(compositeKey);
    } else {
      throw new Error('NoSQL table binding not properly configured');
    }
  }

  static get_instance() {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
}

module.exports.nosql = nosql;

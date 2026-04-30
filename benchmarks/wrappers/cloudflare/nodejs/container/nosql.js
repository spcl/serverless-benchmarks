/**
 * NoSQL module for Cloudflare Node.js Containers.
 *
 * On Cloudflare, NoSQL storage is mapped to KVStore. KVStore 
 * bindings only exist inside the Worker runtime, so a container cannot talk
 * to them directly. Instead, the container forwards each operation over HTTP
 * to the parent Worker (see worker.js), which holds the KVStore
 * binding and performs the actual read/write.
 *
 * Because of this, the HTTP endpoint depends on the Worker's URL, which is
 * not known ahead of time. The handler receives it via the X-Worker-URL
 * header on the incoming request and installs it here through
 * set_worker_url() before any NoSQL call is made.
 */

class nosql {
  constructor() {}

  static worker_url = null; // Set by handler from X-Worker-URL header

  static init_instance(entry) {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
  
  static set_worker_url(url) {
    nosql.worker_url = url;
  }

  async _make_request(operation, params) {
    if (!nosql.worker_url) {
      throw new Error('Worker URL not set - cannot access NoSQL');
    }

    const url = `${nosql.worker_url}/nosql/${operation}`;
    const data = JSON.stringify(params);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data,
      });

      if (!response.ok) {
        let errorMsg;
        try {
          const errorData = await response.json();
          errorMsg = errorData.error || await response.text();
        } catch {
          errorMsg = await response.text();
        }
        throw new Error(`NoSQL operation failed: ${errorMsg}`);
      }

      return await response.json();
    } catch (error) {
      throw new Error(`NoSQL operation failed: ${error.message}`);
    }
  }

  async insert(tableName, primaryKey, secondaryKey, data) {
    const params = {
      table_name: tableName,
      primary_key: primaryKey,
      secondary_key: secondaryKey,
      data: data,
    };
    return this._make_request('insert', params);
  }

  async get(tableName, primaryKey, secondaryKey) {
    const params = {
      table_name: tableName,
      primary_key: primaryKey,
      secondary_key: secondaryKey,
    };
    const result = await this._make_request('get', params);
    return result.data || null;
  }

  async update(tableName, primaryKey, secondaryKey, updates) {
    const params = {
      table_name: tableName,
      primary_key: primaryKey,
      secondary_key: secondaryKey,
      data: updates,
    };
    return this._make_request('update', params);
  }

  async query(tableName, primaryKey, secondaryKeyName) {
    const params = {
      table_name: tableName,
      primary_key: primaryKey,
      secondary_key_name: secondaryKeyName,
    };
    const result = await this._make_request('query', params);
    return result.items || [];
  }

  async delete(tableName, primaryKey, secondaryKey) {
    const params = {
      table_name: tableName,
      primary_key: primaryKey,
      secondary_key: secondaryKey,
    };
    return this._make_request('delete', params);
  }

  static get_instance() {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
}

module.exports.nosql = nosql;

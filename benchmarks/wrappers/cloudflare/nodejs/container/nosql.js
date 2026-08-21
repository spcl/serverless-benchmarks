/**
 * NoSQL module for Cloudflare Node.js Containers.
 *
 * On Cloudflare, NoSQL storage is mapped to KVStore. KVStore bindings only
 * exist inside the Worker runtime, so a container uses the Workers outbound
 * handler through the `http://sebs.kv` virtual host. The handler holds the
 * KV binding and performs the actual read/write.
 *
 */

class nosql {
  constructor() {}

  static outbound_url = 'http://sebs.kv';

  static init_instance(entry) {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
  

  async _make_request(operation, params) {

    const url = `${nosql.outbound_url}/nosql/${operation}`;
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

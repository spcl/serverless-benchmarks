// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const { Datastore, KEY } = require("@google-cloud/datastore");

class nosql {
  constructor(database) {
    this._client = new Datastore({ database });
  }

  _get_entity_key(table_name, primary_key, secondary_key) {
    const parent_key = this._client.key([primary_key[0], primary_key[1]]);
    return this._client.key({
      path: [table_name, secondary_key[1]],
      parent: parent_key,
    });
  }

  async insert(table_name, primary_key, secondary_key, data) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    await this._client.save({ key, data });
  }

  async update(table_name, primary_key, secondary_key, updates) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    let [res] = await this._client.get(key);
    if (!res) {
      res = {};
    }
    Object.assign(res, updates);
    await this._client.save({ key, data: res });
  }

  async get(table_name, primary_key, secondary_key) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    const [res] = await this._client.get(key);
    if (!res) {
      return null;
    }

    // Emulate the kind key
    res[secondary_key[0]] = secondary_key[1];
    // Emulate the main key
    res[primary_key[0]] = primary_key[1];
    return res;
  }

  async query(table_name, primary_key, secondary_key_name) {
    const ancestor = this._client.key([primary_key[0], primary_key[1]]);
    const query = this._client.createQuery(table_name).hasAncestor(ancestor);
    const [res] = await this._client.runQuery(query);

    // Emulate the kind key
    for (const item of res) {
      item[secondary_key_name] = item[KEY].name;
    }

    return res;
  }

  async delete(table_name, primary_key, secondary_key) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    await this._client.delete(key);
  }

  static get_instance(database = null) {
    if (!nosql.instance) {
      if (!database) {
        throw new Error("NoSQL database must be provided when creating an instance.");
      }
      nosql.instance = new nosql(database);
    }
    return nosql.instance;
  }
}
exports.nosql = nosql;

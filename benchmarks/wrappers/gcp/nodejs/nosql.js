// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const { Datastore, KEY } = require("@google-cloud/datastore");

/*
This implementation is the Node.js reimplementation of the reference
implementation in Python. It is used for the NoSQL benchmarks.

Each benchmark supports up to two keys - one for grouping items,
and for unique identification of each item.

In Google Cloud Datastore, we determine different tables by using
its value for `kind` name.

The primary key is assigned to the `kind` value.

To implement sorting semantics, we use the ancestor relation:
the sorting key is used as the parent.
It is the assumption that all related items will have the same parent.
*/

class nosql {
  constructor(database) {
    this._client = new Datastore({ 'databaseId': database });
  }

  _get_entity_key(table_name, primary_key, secondary_key) {
    return this._client.key([
      primary_key[0], primary_key[1], table_name, secondary_key[1]
    ]);
  }

  async insert(table_name, primary_key, secondary_key, data) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    await this._client.save({ key, data });
  }

  async update(table_name, primary_key, secondary_key, updates) {
    // Just like in the Python version, we don't have a direct update.
    // Instead, we fetch the existing data, update fields, and write it.
    // Otherwise, we would also rewrite fields that we do not want to modify.
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

    // Emulate the kind and main keys
    res[secondary_key[0]] = secondary_key[1];
    res[primary_key[0]] = primary_key[1];
    return res;
  }

  async query(table_name, primary_key, secondary_key_name) {
    const ancestor = this._client.key([primary_key[0], primary_key[1]]);
    const query = this._client.createQuery(table_name).hasAncestor(ancestor);
    const [res] = await this._client.runQuery(query);

    // Emulate the kind key
    for (const item of res) {
      item[secondary_key_name] = item[Datastore.KEY].name;
    }

    return res;
  }

  async delete(table_name, primary_key, secondary_key) {
    const key = this._get_entity_key(table_name, primary_key, secondary_key);
    await this._client.delete(key);
  }

  static get_instance(database = null) {
    // There's one database we connect to, so we can preallocate storage instance.
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

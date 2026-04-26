// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const { CosmosClient } = require("@azure/cosmos");

class nosql {
  constructor(url, credential, database) {
    this._client = new CosmosClient({ endpoint: url, key: credential });
    this._db_client = this._client.database(database);
    this._containers = {};
  }

  _get_table(table_name) {
    if (!(table_name in this._containers)) {
      this._containers[table_name] = this._db_client.container(table_name);
    }
    return this._containers[table_name];
  }

  async insert(table_name, primary_key, secondary_key, data) {
    data[primary_key[0]] = primary_key[1];
    // secondary key must have that name in CosmosDB
    data.id = secondary_key[1];

    await this._get_table(table_name).items.upsert(data);
  }

  async get(table_name, primary_key, secondary_key) {
    const { resource } = await this._get_table(table_name)
      .item(secondary_key[1], primary_key[1])
      .read();

    if (!resource) {
      return null;
    }

    resource[secondary_key[0]] = secondary_key[1];

    // remove Azure-specific fields
    delete resource.id;
    delete resource._etag;
    delete resource._rid;
    delete resource._self;
    delete resource._ts;
    delete resource._attachments;

    return resource;
  }

  async update(table_name, primary_key, secondary_key, updates) {
    const ops = [];
    for (const [key, value] of Object.entries(updates)) {
      ops.push({ op: "add", path: `/${key}`, value: value });
    }
    await this._get_table(table_name).item(secondary_key[1], primary_key[1]).patch(ops);
  }

  async query(table_name, primary_key, secondary_key_name) {
    const query = {
      query: `SELECT * FROM c WHERE c.${primary_key[0]} = @keyvalue`,
      parameters: [{ name: "@keyvalue", value: primary_key[1] }],
    };
    const { resources } = await this._get_table(table_name)
      .items.query(query, { enableCrossPartitionQuery: false })
      .fetchAll();

    // Emulate the kind key
    for (const item of resources) {
      item[secondary_key_name] = item.id;
    }

    return resources;
  }

  async delete(table_name, primary_key, secondary_key) {
    await this._get_table(table_name).item(secondary_key[1], primary_key[1]).delete();
  }

  static get_instance(database = null, url = null, credential = null) {
    if (!nosql.instance) {
      if (!database || !url || !credential) {
        throw new Error(
          "NoSQL database, URL and credentials must be provided when creating an instance."
        );
      }
      nosql.instance = new nosql(url, credential, database);
    }
    return nosql.instance;
  }
}
exports.nosql = nosql;

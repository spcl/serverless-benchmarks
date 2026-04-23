// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const aws = require("aws-sdk");

class nosql {
  constructor() {
    if (process.env.NOSQL_STORAGE_TYPE !== "scylladb") {
      throw new Error(`Unsupported NoSQL storage type: ${process.env.NOSQL_STORAGE_TYPE}!`);
    }
    this.client = new aws.DynamoDB.DocumentClient({
      region: "None",
      accessKeyId: "None",
      secretAccessKey: "None",
      endpoint: `http://${process.env.NOSQL_STORAGE_ENDPOINT}`,
      maxRetries: 0,
    });
    this._tables = {};
  }

  _get_table(table_name) {
    if (!(table_name in this._tables)) {
      const env_name = `NOSQL_STORAGE_TABLE_${table_name}`;
      if (env_name in process.env) {
        this._tables[table_name] = process.env[env_name];
      } else {
        throw new Error(
          `Couldn't find an environment variable ${env_name} for table ${table_name}`
        );
      }
    }
    return this._tables[table_name];
  }

  async insert(table_name, primary_key, secondary_key, data) {
    data[primary_key[0]] = primary_key[1];
    data[secondary_key[0]] = secondary_key[1];
    await this.client
      .put({ TableName: this._get_table(table_name), Item: data })
      .promise();
  }

  async get(table_name, primary_key, secondary_key) {
    const key = {};
    key[primary_key[0]] = primary_key[1];
    key[secondary_key[0]] = secondary_key[1];
    const res = await this.client
      .get({ TableName: this._get_table(table_name), Key: key })
      .promise();
    return res.Item;
  }

  async update(table_name, primary_key, secondary_key, updates) {

    const key = {};
    key[primary_key[0]] = primary_key[1];
    key[secondary_key[0]] = secondary_key[1];

    const update_names = {};
    const update_values = {};
    const update_expression = ["SET"];
    for (const [key_name, value] of Object.entries(updates)) {
      update_expression.push(`#${key_name}_name = :${key_name}_value,`);
      update_names[`#${key_name}_name`] = key_name;
      update_values[`:${key_name}_value`] = value;
    }
    update_expression[update_expression.length - 1] = update_expression[
      update_expression.length - 1
    ].slice(0, -1);

    await this.client
      .update({
        TableName: this._get_table(table_name),
        Key: key,
        UpdateExpression: update_expression.join(" "),
        ExpressionAttributeNames: update_names,
        ExpressionAttributeValues: update_values,
      })
      .promise();
  }

  async query(table_name, primary_key, _) {
    const key_name = primary_key[0];
    const res = await this.client
      .query({
        TableName: this._get_table(table_name),
        KeyConditionExpression: "#key_name = :keyvalue",
        ExpressionAttributeNames: { "#key_name": key_name },
        ExpressionAttributeValues: { ":keyvalue": primary_key[1] },
      })
      .promise();
    return res.Items;
  }

  async delete(table_name, primary_key, secondary_key) {
    const key = {};
    key[primary_key[0]] = primary_key[1];
    key[secondary_key[0]] = secondary_key[1];
    await this.client
      .delete({ TableName: this._get_table(table_name), Key: key })
      .promise();
  }

  static get_instance() {
    if (!nosql.instance) {
      nosql.instance = new nosql();
    }
    return nosql.instance;
  }
}
exports.nosql = nosql;

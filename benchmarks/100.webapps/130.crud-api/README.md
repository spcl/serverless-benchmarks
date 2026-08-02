# 130.crud-api - CRUD API

**Type:** Webapps
**Languages:** Python, Node.js
**Architecture:** x64, arm64

## Description

The benchmark implements a simple CRUD application simulating a webstore cart. It offers three basic methods: add new item (`PUT`), get an item (`GET`), and query all items in a cart. It uses the NoSQL storage, with each item stored using cart id as primary key and item id as secondary key. The Python implementation uses cloud-native libraries to access the database.

On AWS, the identity running SeBS must be allowed to create, describe, seed, and clean up the benchmark's DynamoDB table. SeBS grants the required item reads, writes, and queries to its default Lambda execution role; custom roles must provide them explicitly. See the AWS section of the [platform documentation](../../../docs/platforms.md) for the exact actions.

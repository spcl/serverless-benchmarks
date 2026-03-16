# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
# 130.crud-api - CRUD API

**Type:** Webapps
**Languages:** Python
**Architecture:** x64, arm64

## Description

The benchmark implements a simple CRUD application simulating a webstore cart. It offers three basic methods: add new item (`PUT`), get an item (`GET`), and query all items in a cart. It uses the NoSQL storage, with each item stored using cart id as primary key and item id as secondary key. The Python implementation uses cloud-native libraries to access the database.

// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const minio = require('minio'),
      path = require('path'),
      uuid = require('uuid'),
      util = require('util'),
      fs = require('fs'),
      stream = require('stream');

class minio_storage {

  constructor() {
    let address = process.env.MINIO_ADDRESS;
    let access_key = process.env.MINIO_ACCESS_KEY;
    let secret_key = process.env.MINIO_SECRET_KEY;
    this.client = new minio.Client(
      {
        endPoint: address.split(':')[0],
        port: parseInt(address.split(':')[1], 10),
        accessKey: access_key,
        secretKey: secret_key,
        useSSL: false
      }
    );
  }

  unique_name(file) {
    let name = path.parse(file);
    let uuid_name = uuid.v4().split('-')[0];
    return path.join(name.dir, util.format('%s.%s%s', name.name, uuid_name, name.ext));
  }

  upload(bucket, file, filepath) {
    let uniqueName = this.unique_name(file);
    return [uniqueName, this.client.fPutObject(bucket, uniqueName, filepath)];
  };

  download(bucket, file, filepath) {
    return this.client.fGetObject(bucket, file, filepath);
  };

  async downloadDirectory(bucket, prefix, downloadPath) {

    const stream = this.client.listObjectsV2(bucket, prefix, true);

    const downloadPromises = [];
    for await (const obj of stream) {
      try {
        console.log(obj)
        const fileName = obj.name;
        const pathToFile = path.dirname(fileName);
        fs.mkdirSync(path.join(downloadPath, pathToFile), { recursive: true });
        downloadPromises.push(this.download(bucket, fileName, path.join(downloadPath, fileName)));
      } catch (err) {
        throw new Error(`Error downloading ${obj.name}: ${err}`);
      }
    }
    await Promise.all(downloadPromises);
  };

  uploadStream(bucket, file) {
    var write_stream = new stream.PassThrough();
    let uniqueName = this.unique_name(file);
    let promise = this.client.putObject(bucket, uniqueName, write_stream, write_stream.size);
    return [write_stream, promise, uniqueName];
  };

  downloadStream(bucket, file) {
    var read_stream = new stream.PassThrough();
    return this.client.getObject(bucket, file);
  };

  static get_instance() {
    if(!this.instance) {
      this.instance = new storage();
    }
    return this.instance;
  }


};
exports.storage = minio_storage;

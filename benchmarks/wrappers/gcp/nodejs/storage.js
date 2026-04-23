// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
const { Storage } = require('@google-cloud/storage'),
        fs = require('fs'),
        path = require('path'),
        uuid = require('uuid'),
        util = require('util'),
        stream = require('stream');

class gcp_storage {

  constructor() {
    this.storage = new Storage();
  }

  unique_name(file) {
    let name = path.parse(file);
    let uuid_name = uuid.v4().split('-')[0];
    return path.join(name.dir, util.format('%s.%s%s', name.name, uuid_name, name.ext));
  }

  upload(container, file, filepath) {
    let bucket = this.storage.bucket(container);
    let uniqueName = this.unique_name(file);
    let options = {destination: uniqueName, resumable: false};
    return [uniqueName, bucket.upload(filepath, options)];
  };

  download(container, file, filepath) {
    let bucket = this.storage.bucket(container);
    var file = bucket.file(file);
    return file.download({destination: filepath});
  };

  async downloadDirectory(container, prefix, downloadPath) {
    let bucket = this.storage.bucket(container);
    const [files] = await bucket.getFiles({ prefix: prefix });

    const downloadPromises = files.map(file => {
      const fileName = file.name;
      const pathToFile = path.dirname(fileName);
      fs.mkdirSync(path.join(downloadPath, pathToFile), { recursive: true });
      return this.download(container, fileName, path.join(downloadPath, fileName));
    });

    await Promise.all(downloadPromises);
  };

  uploadStream(container, file) {
    let bucket = this.storage.bucket(container);
    let uniqueName = this.unique_name(file);
    var file = bucket.file(uniqueName);
    let upload = file.createWriteStream();
    var write_stream = new stream.PassThrough();

    write_stream.pipe(upload);

    const promise = new Promise((resolve, reject) => {
      upload.on('error', err => {
        upload.end();
        reject(err);
      });

      upload.on('finish', () => {
        upload.end();
        resolve(file.name);
      });
    });
    return [write_stream, promise, uniqueName];
  };

  downloadStream(container, file) {
    let bucket = this.storage.bucket(container);
    var file = bucket.file(file);
    let downloaded = file.createReadStream();
    return Promise.resolve(downloaded);
  };
};
exports.storage = gcp_storage;

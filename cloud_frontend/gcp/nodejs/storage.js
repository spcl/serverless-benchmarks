const { Storage } = require('@google-cloud/storage'),
        fs = require('fs'),
        uuid = require('uuid'),
        util = require('util'),
        stream = require('stream');

class gcp_storage {

  constructor() {
    this.storage = storage();
  }

  unique_name(file) {
    let [name, extension] = file.split('.');
    let uuid_name = uuid.v4().split('-')[0];
    return util.format('%s.%s.%s', name, uuid_name, extension);
  }

  upload(container, file, filepath) {
    bucket = this.storage.bucket(container);
    let uniqueName = this.unique_name(file);
    let options = {destination: uniqueName};
    return [unique_name, bucket.upload(uniqueName, options)];
  };

  download(bucket, file, filepath) {
    let bucket = this.storage.bucket(container);
    var file = bucket.file(file);
    file.download({destination: filepath});
  };

  uploadStream(container, file) {
    let bucket = this.storage.bucket(container);
    let uniqueName = this.unique_name(file);
    var file = bucket.file(uniqueName);
    let upload = file.createWriteStream();
    var write_stream = new stream.PassThrough();
    write_stream.pipe(upload);
    return [write_stream, Promise.resolve(upload), unique_name];
  };

  downloadStream(container, file) {
    let bucket = this.storage.bucket(container);
    var file = bucket.file(file);
    let downloaded = file.createReadStream();
    return Promise.resolve(downloaded);
  };
};
exports.storage = gcp_storage;
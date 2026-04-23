// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

const fs = require('fs'), path = require('path'), uuid = require('uuid'), util = require('util'), stream = require('stream');

const { pipeline } = require("stream/promises");

const { Upload } = require('@aws-sdk/lib-storage');
const { S3, GetObjectCommand, ListObjectsV2Command} = require('@aws-sdk/client-s3');

class aws_storage {

  constructor() {
    this.S3 = new S3();
  }

  unique_name(file) {
    let name = path.parse(file);
    let uuid_name = uuid.v4().split('-')[0];
    return path.join(name.dir, util.format('%s.%s%s', name.name, uuid_name, name.ext));
  }

  upload(bucket, file, filepath) {
    var upload_stream = fs.createReadStream(filepath);
    let uniqueName = this.unique_name(file);
    let params = {Bucket: bucket, Key: uniqueName, Body: upload_stream};
    var upload = new Upload({
      client: this.S3,
      params
    });
    return [uniqueName, upload.done()];
  };

  async download(bucket, file, filepath) {
    var file_stream = fs.createWriteStream(filepath);
    const response = await this.S3.send(new GetObjectCommand({ Bucket: bucket, Key: file }));
    await pipeline(response.Body, file_stream);
  };

  async downloadDirectory(bucket, prefix, downloadPath) {
    const response = await this.S3.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix }));

    if (!response.Contents) {
      throw new Error(`No objects found in bucket '${bucket}' with prefix '${prefix}'`);
    }

    const downloadPromises = response.Contents.map(obj => {
      const fileName = obj.Key;
      const pathToFile = path.dirname(fileName);
      fs.mkdirSync(path.join(downloadPath, pathToFile), { recursive: true });
      return this.download(bucket, fileName, path.join(downloadPath, fileName));
    });

    await Promise.all(downloadPromises);
  };

  uploadStream(bucket, file) {
    var write_stream = new stream.PassThrough();
    let uniqueName = this.unique_name(file);
    // putObject won't work correctly for streamed data (length has to be known before)
    // https://stackoverflow.com/questions/38442512/difference-between-upload-and-putobject-for-uploading-a-file-to-s3
    var upload = new Upload({
      client: this.S3,
      params: {Bucket: bucket, Key: uniqueName, Body: write_stream}
    });
    return [write_stream, upload.done(), uniqueName];
  };

  // We return a promise to match the API for other providers
  downloadStream(bucket, file) {
    return this.S3.send(new GetObjectCommand({
      Bucket: bucket,
      Key: file
    })).then(response => response.Body);
  };
}
exports.storage = aws_storage;

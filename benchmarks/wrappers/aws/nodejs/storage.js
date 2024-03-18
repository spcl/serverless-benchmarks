
const aws = require('aws-sdk'),
      fs = require('fs'),
      path = require('path'),
      uuid = require('uuid'),
      util = require('util'),
      stream = require('stream');

class aws_storage {

  constructor() {
    this.S3 = new aws.S3();
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
    var upload = this.S3.upload(params);
    return [uniqueName, upload.promise()];
  };

  download(bucket, file, filepath) {
    var file = fs.createWriteStream(filepath);
    this.S3.getObject( {Bucket: bucket, Key: file} ).createReadStream().pipe(file);
  };

  uploadStream(bucket, file) {
    var write_stream = new stream.PassThrough();
    let uniqueName = this.unique_name(file);
    // putObject won't work correctly for streamed data (length has to be known before)
    // https://stackoverflow.com/questions/38442512/difference-between-upload-and-putobject-for-uploading-a-file-to-s3
    var upload = this.S3.upload( {Bucket: bucket, Key: uniqueName, Body: write_stream} );
    return [write_stream, upload.promise(), uniqueName];
  };

  // We return a promise to match the API for other providers
  downloadStream(bucket, file) {
    // AWS.Request -> read stream
    let downloaded = this.S3.getObject( {Bucket: bucket, Key: file} ).createReadStream();
    return Promise.resolve(downloaded);
  };
};
exports.storage = aws_storage;

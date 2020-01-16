
const aws = require('aws-sdk'),
      stream = require('stream');

class aws_storage {

  constructor() {
    this.S3 = new aws.S3();
  }

  upload(bucket, file, filepath) {
  };

  download(bucket, file, filepath) {
  };

  uploadStream(bucket, file) {
    var write_stream = new stream.PassThrough();
    // putObject won't work correctly for streamed data (length has to be known before)
    // https://stackoverflow.com/questions/38442512/difference-between-upload-and-putobject-for-uploading-a-file-to-s3
    var upload = this.S3.upload( {Bucket: bucket, Key: file, Body: write_stream} );
    return [write_stream, upload.promise()];
  };

  // We return a promise to match the API for other providers
  downloadStream(bucket, file) {
    // AWS.Request -> read stream
    let downloaded = this.S3.getObject( {Bucket: bucket, Key: file} ).createReadStream();
    return Promise.resolve(downloaded);
  };
};
exports.storage = aws_storage;

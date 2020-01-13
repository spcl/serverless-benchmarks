
const minio = require('minio'),
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

  upload(bucket, file, filepath) {
    this.client.fPutObject(bucket, file, filepath);
  };

  download(bucket, file, filepath) {
    this.client.fGetObject(bucket, file, filepath);

  };

  uploadStream(bucket, file) {
    var write_stream = new stream.PassThrough();
    let promise = this.client.putObject(bucket, file, write_stream, write_stream.size);
    return [write_stream, promise];
  };

  downloadStream(bucket, file) {
    var read_stream = new stream.PassThrough();
    this.client.getObject(bucket, file,
      (err, stream) => {
        if(err) throw err;
        stream.pipe(read_stream);
      }
    );
    return read_stream;
  };

  static get_instance() {
    if(!this.instance) {
      this.instance = new storage();
    }
    return this.instance;
  }


};
exports.storage = minio_storage;

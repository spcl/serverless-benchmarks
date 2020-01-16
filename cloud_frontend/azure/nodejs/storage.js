
const { BlobServiceClient } = require('@azure/storage-blob'),
        stream = require('stream');


class azure_storage {

  constructor() {
    const STORAGE_CONNECTION_STRING = process.env.STORAGE_CONNECTION_STRING;   
    this.client = BlobServiceClient.fromConnectionString(STORAGE_CONNECTION_STRING);
  }

  upload(bucket, file, filepath) {
    // TOD:
  };

  download(bucket, file, filepath) {
    // TODO:
  };

  // We could provide additional API for just providing a byte buffer and uploading
  // Right now streams seems to be nicer
  uploadStream(container, file) {
    // it seems that JS does not have an API that would allow to
    // upload/download data without going through container/blob client 
    let containerClient = this.client.getContainerClient(container);
    let blockBlobClient = containerClient.getBlockBlobClient(file);
    var write_stream = new stream.PassThrough();
    // returns promise
    let upload = blockBlobClient.uploadStream(write_stream);
    return [write_stream, upload];
  };

  downloadStream(container, file) {
    let containerClient = this.client.getContainerClient(container);
    let blockBlobClient = containerClient.getBlockBlobClient(file);
    return blockBlobClient.download().then(
        (data) => {
          return data.readableStreamBody;
        }
    );
  };
};
exports.storage = azure_storage;

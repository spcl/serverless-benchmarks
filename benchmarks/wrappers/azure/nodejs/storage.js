
const { BlobServiceClient } = require('@azure/storage-blob'),
        path = require('path'),
        uuid = require('uuid'),
        util = require('util'),
        stream = require('stream');


class azure_storage {

  constructor() {
    const STORAGE_CONNECTION_STRING = process.env.STORAGE_CONNECTION_STRING;   
    this.client = BlobServiceClient.fromConnectionString(STORAGE_CONNECTION_STRING);
  }

  unique_name(file) {
    let name = path.parse(file);
    let uuid_name = uuid.v4().split('-')[0];
    return path.join(name.dir, util.format('%s.%s%s', name.name, uuid_name, name.ext));
  }

  upload(container, file, filepath) {
    // it seems that JS does not have an API that would allow to
    // upload/download data without going through container/blob client 
    let containerClient = this.client.getContainerClient(container);
    let uniqueName = this.unique_name(file);
    let blockBlobClient = containerClient.getBlockBlobClient(uniqueName);
    return [uniqueName, blockBlobClient.uploadFile(filepath)];
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
    let uniqueName = this.unique_name(file);
    let blockBlobClient = containerClient.getBlockBlobClient(uniqueName);
    var write_stream = new stream.PassThrough();
    // returns promise
    let upload = blockBlobClient.uploadStream(write_stream);
    return [write_stream, upload, uniqueName];
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

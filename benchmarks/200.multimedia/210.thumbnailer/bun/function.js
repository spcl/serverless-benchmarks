const sharp = require('sharp'),
			path = require('path'),
      storage = require('./storage');

let storage_handler = new storage.storage();

exports.handler = async function(event) {

  bucket = event.bucket.bucket
  input_prefix = event.bucket.input
  output_prefix = event.bucket.output
  let key = event.object.key
  width = event.object.width
  height = event.object.height
  let pos = key.lastIndexOf('.');
  let upload_key = key.substr(0, pos < 0 ? key.length : pos) + '.png';

  const sharp_resizer = sharp().resize(width, height).png();
  let read_promise = storage_handler.downloadStream(bucket, path.join(input_prefix, key));
  let [writeStream, promise, uploadName] = storage_handler.uploadStream(bucket, path.join(output_prefix, upload_key));
  read_promise.then(
    (input_stream) => {
      input_stream.pipe(sharp_resizer).pipe(writeStream);
    }
  );
  await promise;
  return {bucket: output_prefix, key: uploadName}
};

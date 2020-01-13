const sharp = require('sharp'),
			path = require('path'),
      storage = require('./storage');

let storage_handler = new storage.storage();

exports.handler = async function(event) {
  input_bucket = event.bucket.input
  output_bucket = event.bucket.output
  key = event.object.key
  width = event.object.width
  height = event.object.height

  const sharp_resizer = sharp().resize(width, height).png();
  let input_data = storage_handler.downloadStream(input_bucket, key);
  let [writeStream, promise] = storage_handler.uploadStream(output_bucket, key);
  input_data.pipe(sharp_resizer).pipe(writeStream);
  await promise;
};

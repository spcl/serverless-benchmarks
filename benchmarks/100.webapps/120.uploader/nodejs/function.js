const fs = require('fs'),
      path = require('path'),
      request = require('request'),
      storage = require('./storage');

let storage_handler = new storage.storage();

function streamToPromise(stream) {
  return new Promise(function(resolve, reject) {
    stream.on("close", () =>  {
      resolve();
    });
    stream.on("error", reject);
  })
}

exports.handler = async function(event) {
  let bucket = event.bucket.bucket
  let output_prefix = event.bucket.output
  let url = event.object.url
  let upload_key = path.basename(url)
  let download_path = path.join('/tmp', upload_key)

  var file = fs.createWriteStream(download_path);
  request(url).pipe(file);
  let promise = streamToPromise(file);
  var keyName;
  let upload = promise.then(
    async () => {
      [keyName, promise] = storage_handler.upload(bucket, path.join(output_prefix, upload_key), download_path);
      await promise;
    }
  );
  await upload;
  return {bucket: bucket, url: url, key: keyName}
};

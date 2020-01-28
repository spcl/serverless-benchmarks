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
  let output_bucket = event.bucket.output
  let url = event.object.url
  let upload_key = path.basename(url)
  let download_path = path.join('/tmp', upload_key)

  var file = fs.createWriteStream(download_path);
  request(url).pipe(file);
  let promise = streamToPromise(file);
  let upload = promise.then(
    async () => {
      await storage_handler.upload(output_bucket, upload_key, download_path);
    }
  );
  await upload;
  return {bucket: output_bucket, key: upload_key}
};

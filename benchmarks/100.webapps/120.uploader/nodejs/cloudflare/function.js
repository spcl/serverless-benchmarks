// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
// Cloudflare Workers differ from the default Node.js version: Workers require
// ES module syntax (no CommonJS `require`) and do not ship the `request` npm
// package, so we use the platform-native `fetch` API and buffer the response
// into /tmp instead of piping a stream.
import * as fs from 'node:fs';
import * as path from 'node:path';
import { storage } from './storage';

let storage_handler = new storage();

export const handler = async function(event) {
  let bucket = event.bucket.bucket;
  let output_prefix = event.bucket.output;
  let url = event.object.url;
  let upload_key = path.basename(url);
  let download_path = path.join('/tmp', upload_key);

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'SeBS/1.2 (https://github.com/spcl/serverless-benchmarks) SeBS Benchmark Suite/1.2'
    }
  });
  const buffer = await response.arrayBuffer();
  fs.writeFileSync(download_path, Buffer.from(buffer));

  let [keyName, uploadPromise] = storage_handler.upload(
    bucket,
    path.join(output_prefix, upload_key),
    download_path
  );
  await uploadPromise;

  return {result: {bucket: bucket, url: url, key: keyName}};
};

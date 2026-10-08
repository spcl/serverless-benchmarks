// Cloudflare Workers variant: replaces archiver (which relies on Node streams
// and prototype inheritance that breaks under Workers) with fflate, a pure-JS
// zip library that runs without any Node-specific APIs.
import * as fs from 'node:fs';
import * as path from 'node:path';
import { zipSync, strToU8 } from 'fflate';
import { v4 as uuidv4 } from 'uuid';
import { storage } from './storage';

let storage_handler = new storage();

function parseDirectory(directory) {
  let size = 0;
  function walkDir(dir) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const filepath = path.join(dir, file);
      const stat = fs.statSync(filepath);
      if (stat.isDirectory()) {
        walkDir(filepath);
      } else {
        size += stat.size;
      }
    }
  }
  walkDir(directory);
  return size;
}

function collectFiles(directory) {
  const result = {};
  function walkDir(dir, prefix) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const filepath = path.join(dir, file);
      const relPath = prefix ? `${prefix}/${file}` : file;
      const stat = fs.statSync(filepath);
      if (stat.isDirectory()) {
        walkDir(filepath, relPath);
      } else {
        result[relPath] = [fs.readFileSync(filepath), { level: 9 }];
      }
    }
  }
  walkDir(directory, '');
  return result;
}

export const handler = async function(event) {
  const bucket = event.bucket.bucket;
  const input_prefix = event.bucket.input;
  const output_prefix = event.bucket.output;
  const key = event.object.key;

  const download_path = path.join('/tmp', `${key}-${uuidv4()}`);
  fs.mkdirSync(download_path, { recursive: true });

  const s3_download_begin = Date.now();
  await storage_handler.downloadDirectory(bucket, path.join(input_prefix, key), download_path);
  const s3_download_stop = Date.now();

  const size = parseDirectory(download_path);

  const compress_begin = Date.now();
  const archive_name = `${key}.zip`;
  const archive_path = path.join('/tmp', archive_name);
  const files = collectFiles(download_path);
  const zipped = zipSync(files);
  fs.writeFileSync(archive_path, zipped);
  const compress_end = Date.now();

  const archive_size = fs.statSync(archive_path).size;

  const s3_upload_begin = Date.now();
  const [key_name, uploadPromise] = storage_handler.upload(
    bucket,
    path.join(output_prefix, archive_name),
    archive_path
  );
  await uploadPromise;
  const s3_upload_stop = Date.now();

  const download_time = (s3_download_stop - s3_download_begin) * 1000;
  const upload_time = (s3_upload_stop - s3_upload_begin) * 1000;
  const process_time = (compress_end - compress_begin) * 1000;

  return {
    result: {
      bucket: bucket,
      key: key_name
    },
    measurement: {
      download_time: download_time,
      download_size: size,
      upload_time: upload_time,
      upload_size: archive_size,
      compute_time: process_time
    }
  };
};

const fs = require('fs');
const path = require('path');
const archiver = require('archiver');
const { v4: uuidv4 } = require('uuid');
const storage = require('./storage');

let storage_handler = new storage.storage();

/**
 * Calculate total size of a directory recursively
 * @param {string} directory - Path to directory
 * @returns {number} Total size in bytes
 */
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

/**
 * Create a zip archive from a directory using archiver
 * @param {string} sourceDir - Directory to compress
 * @param {string} outputPath - Path for the output archive file
 * @returns {Promise<void>}
 */
async function createZipArchive(sourceDir, outputPath) {
  return new Promise((resolve, reject) => {
    const output = fs.createWriteStream(outputPath);
    const archive = archiver('zip', {
      zlib: { level: 9 } // Maximum compression
    });

    output.on('close', () => {
      resolve();
    });

    archive.on('error', (err) => {
      reject(err);
    });

    archive.pipe(output);

    // Add all files from the directory, excluding the archive itself
    archive.glob('**/*', {
      cwd: sourceDir,
      ignore: [path.basename(outputPath)]
    });

    archive.finalize();
  });
}

exports.handler = async function(event) {
  const bucket = event.bucket.bucket;
  const input_prefix = event.bucket.input;
  const output_prefix = event.bucket.output;
  const key = event.object.key;
  
  // Create unique download path
  const download_path = path.join('/tmp', `${key}-${uuidv4()}`);
  fs.mkdirSync(download_path, { recursive: true });

  // Download directory from storage
  const s3_download_begin = Date.now();
  await storage_handler.downloadDirectory(bucket, path.join(input_prefix, key), download_path);
  const s3_download_stop = Date.now();
  
  // Calculate size of downloaded files
  const size = parseDirectory(download_path);

  // Compress directory
  const compress_begin = Date.now();
  const archive_name = `${key}.zip`;
  const archive_path = path.join(download_path, archive_name);
  await createZipArchive(download_path, archive_path);
  const compress_end = Date.now();

  // Get archive size
  const archive_size = fs.statSync(archive_path).size;

  // Upload compressed archive
  const s3_upload_begin = Date.now();
  const [key_name, uploadPromise] = storage_handler.upload(
    bucket, 
    path.join(output_prefix, archive_name), 
    archive_path
  );
  await uploadPromise;
  const s3_upload_stop = Date.now();

  // Calculate times in microseconds
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


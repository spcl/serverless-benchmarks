const fs = require('fs');
const path = require('path');
const storage = require('./storage');
const { execFile } = require('child_process');
const { promisify } = require('util');
const execFileAsync = promisify(execFile);

const storage_handler = new storage.storage();
const SCRIPT_DIR = path.resolve(__dirname);

async function callFfmpeg(args) {
	try {
		const ffmpegPath = path.join(SCRIPT_DIR, 'ffmpeg', 'ffmpeg');
		const { stdout, stderr } = await execFileAsync(ffmpegPath, ['-y', ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
	} catch (error) {
		throw new Error(`Invocation of ffmpeg failed! ${error.message}`);
	}
}

async function toGif(video, duration) {
	const output = `/tmp/processed-${path.basename(video)}.gif`;
	await callFfmpeg(['-i', video, '-t', `${duration}`, '-vf', 'fps=10,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse', '-loop', '0', output]);
	return output;
}

async function watermark(video, duration) {
	const output = `/tmp/processed-${path.basename(video)}`;
	const watermarkFile = path.join(SCRIPT_DIR, 'resources', 'watermark.png');
	await callFfmpeg(['-i', video, '-i', watermarkFile, '-t', `${duration}`, '-filter_complex', 'overlay=main_w/2-overlay_w/2:main_h/2-overlay_h/2', output]);
	return output;
}

async function transcodeMp3(video, duration) {
	// Implement the transcode_mp3 function if necessary
}

const operations = { 'transcode': transcodeMp3, 'extract-gif': toGif, 'watermark': watermark };

exports.handler = async function(event) {
	try {
		const bucket = event.bucket.bucket;
		const input_prefix = event.bucket.input;
		const output_prefix = event.bucket.output;
		const key = event.object.key;
		const duration = event.object.duration;
		const op = event.object.op;
		const download_path = `/tmp/${key}`;

		const ffmpegBinary = path.join(SCRIPT_DIR, 'ffmpeg', 'ffmpeg');
		try {
			fs.chmodSync(ffmpegBinary, '755');
		} catch (error) {
			console.error('Error setting executable permissions for ffmpeg:', error.message);
		}

		const downloadBegin = Date.now();
		await storage_handler.download(bucket, path.join(input_prefix, key), download_path);
		const downloadSize = fs.statSync(download_path).size;
		const downloadStop = Date.now();

		const processBegin = Date.now();
		const upload_path = await operations[op](download_path, duration);
		const processEnd = Date.now();

		const uploadBegin = Date.now();
		const filename = path.basename(upload_path);
		const uploadSize = fs.statSync(upload_path).size;
		const uploadKey = await storage_handler.upload(bucket, path.join(output_prefix, filename), upload_path);
		const uploadStop = Date.now();

		const downloadTime = (downloadStop - downloadBegin) * 1000;
		const uploadTime = (uploadStop - uploadBegin) * 1000;
		const processTime = (processEnd - processBegin) * 1000;

		console.log({
			download_time: downloadTime,
			download_size: downloadSize,
			upload_time: uploadTime,
			upload_size: uploadSize,
			process_time: processTime
		});

		return {
			result: {
				bucket: bucket,
				key: uploadKey
			},
			measurement: {
				download_time: downloadTime,
				download_size: downloadSize,
				upload_time: uploadTime,
				upload_size: uploadSize,
				compute_time: processTime
			}
		};
	} catch (err) {
		console.error('Handler error:', err);
		throw err;
	}
};

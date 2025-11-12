const dgram = require('dgram');
const fs = require('fs');
const path = require('path');
const storage = require('./storage');

const storage_handler = new storage.storage();

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

exports.handler = async function(event) {
  const requestId = event['request-id'];
  const address = event['server-address'];
  const port = event['server-port'];
  const repetitions = event['repetitions'];
  const outputBucket = event.bucket.bucket;
  const outputPrefix = event.bucket.output;
  
  const times = [];
  let i = 0;
  const client = dgram.createSocket('udp4');
  client.bind();
  
  const message = Buffer.from(String(requestId));
  let consecutiveFailures = 0;
  let key = null;

  while (i < repetitions + 1) {
    try {
      const sendBegin = Date.now() / 1000;
      
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Socket timeout'));
        }, 3000);

        client.send(message, port, address, (err) => {
          if (err) {
            clearTimeout(timeout);
            reject(err);
          }
        });

        client.once('message', (msg, rinfo) => {
          clearTimeout(timeout);
          const recvEnd = Date.now() / 1000;
          resolve(recvEnd);
        });
      }).then((recvEnd) => {
        if (i > 0) {
          times.push([i, sendBegin, recvEnd]);
        }
        i++;
        consecutiveFailures = 0;
      });
    } catch (err) {
      i++;
      consecutiveFailures++;
      if (consecutiveFailures === 5) {
        console.log("Can't setup the connection");
        break;
      }
      continue;
    }
  }

  client.close();

  if (consecutiveFailures !== 5) {
    // Write CSV file using stream
    const csvPath = '/tmp/data.csv';
    let csvContent = 'id,client_send,client_rcv\n';
    times.forEach(row => {
      csvContent += row.join(',') + '\n';
    });
    
    // Use createWriteStream and wait for it to finish
    await new Promise((resolve, reject) => {
      const writeStream = fs.createWriteStream(csvPath);
      writeStream.write(csvContent);
      writeStream.end();
      writeStream.on('finish', resolve);
      writeStream.on('error', reject);
    });

    const filename = `results-${requestId}.csv`;
    let uploadPromise;
    [key, uploadPromise] = storage_handler.upload(outputBucket, path.join(outputPrefix, filename), csvPath);
    await uploadPromise;
  }

  return { result: key };
};

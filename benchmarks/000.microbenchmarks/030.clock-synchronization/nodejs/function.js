const dgram = require('dgram');
const fs = require('fs');
const path = require('path');
const storage = require('./storage');

const storage_handler = new storage.storage();

exports.handler = async function(event) {
  const requestId = event['request-id'];
  const address = event['server-address'];
  const port = event['server-port'];
  const repetitions = event['repetitions'];
  const outputBucket = event.bucket.bucket;
  const outputPrefix = event.bucket.output;
  
  const times = [];
  console.log(`Starting communication with ${address}:${port}`);
  
  let i = 0;
  const client = dgram.createSocket('udp4');
  client.bind();
  
  let message = Buffer.from(String(requestId));
  let consecutiveFailures = 0;
  let measurementsNotSmaller = 0;
  let curMin = 0;
  let key = null;

  while (i < 1000) {
    try {
      const sendBegin = Date.now() / 1000;
      
      const recvEnd = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Socket timeout'));
        }, 4000);

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
      });

      if (i > 0) {
        times.push([i, sendBegin, recvEnd]);
      }

      const curTime = recvEnd - sendBegin;
      console.log(`Time ${curTime} Min Time ${curMin} NotSmaller ${measurementsNotSmaller}`);

      if (curTime > curMin && curMin > 0) {
        measurementsNotSmaller++;
        if (measurementsNotSmaller === repetitions) {
          message = Buffer.from('stop');
          client.send(message, port, address);
          break;
        }
      } else {
        curMin = curTime;
        measurementsNotSmaller = 0;
      }

      i++;
      consecutiveFailures = 0;
    } catch (err) {
      i++;
      consecutiveFailures++;
      if (consecutiveFailures === 7) {
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

  return { 
    result: { 
      'bucket-key': key, 
      'timestamp': event['income-timestamp'] 
    } 
  };
};

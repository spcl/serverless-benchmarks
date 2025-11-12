const net = require('net');

exports.handler = async function(event) {
  const address = event['ip-address'];
  const port = event['port'];

  return new Promise((resolve, reject) => {
    const client = new net.Socket();
    
    client.setTimeout(20000);
    
    client.connect(port, address, () => {
      console.log('Connected to server');
    });

    client.on('data', (data) => {
      const msg = data.toString();
      client.destroy();
      resolve({ result: msg });
    });

    client.on('timeout', () => {
      client.destroy();
      reject(new Error('Connection timeout'));
    });

    client.on('error', (err) => {
      reject(err);
    });
  });
};

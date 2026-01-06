const http = require('http'),
      strftime = require('strftime'),
      express = require('express'),
      f = require('/function/function/function');
//import { v4 as uuidv4 } from 'uuid';
const { v4: uuidv4 } = require('uuid');


var app = express();
app.use(express.json());

app.post('/alive', function (req, res) {
  res.send(JSON.stringify({
    status: "ok"
  }));
});

app.post('/', function (req, res) {

  // SonataFlow sends requests wrapped in {"payload": ...}
  // Unwrap the payload before passing to the function
  let function_input = req.body;
  if (req.body && typeof req.body === 'object' && Object.prototype.hasOwnProperty.call(req.body, 'payload')) {
    function_input = req.body.payload;
  }

  let ret = f.handler(function_input);
  ret.then((func_res) => {
    let output = func_res;
    if (func_res && typeof func_res === 'object' && Object.prototype.hasOwnProperty.call(func_res, 'payload')) {
      output = func_res.payload;
    }
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(output));
  },
  (reason) => {
    console.error('Function invocation failed!');
    console.error('Request body:', JSON.stringify(req.body, null, 2));
    console.error('Error:', reason);
    res.status(500).json({
      error: reason.message || String(reason),
      stack: reason.stack
    });
  }
  );
});

app.listen(port=process.argv[2], function () {
  console.log(`Server listening on port ${process.argv[2]}.`);
});


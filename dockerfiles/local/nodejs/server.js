const http = require('http'),
      strftime = require('strftime'),
      express = require('express'),
      f = require('/function/function/function');
//import { v4 as uuidv4 } from 'uuid';
const { v4: uuidv4 } = require('uuid');


var app = express();
app.use(express.json());

app.post('/', function (req, res) {

  let begin = Date.now();
  let ret = f.handler(req.body);
  ret.then((func_res) => {

    let end = Date.now();
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({
      begin: strftime('%s.%L', new Date(begin)),
      end: strftime('%s.%L', new Date(end)),
      request_id: uuidv4(),
      is_cold: false,
      result: {
        output: func_res
      }
    }));
  },
  (reason) => {
    console.log('Function invocation failed!');
    console.log(reason);
    process.exit(1);
  }
  );
});

app.listen(port=process.argv[2], function () {
  console.log(`Server listening on port ${process.argv[2]}.`);
});



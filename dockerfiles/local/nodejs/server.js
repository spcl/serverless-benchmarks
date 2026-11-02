const http = require('http'),
      strftime = require('strftime'),
      express = require('express'),
      f = require('/function/function/function'),
      environment = require('/function/function/environment');
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

  let begin = Date.now();
  let ret = f.handler(req.body);
  ret.then((func_res) => {

    let end = Date.now();
    const env = environment.collect();
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({
      begin: strftime('%s.%L', new Date(begin)),
      end: strftime('%s.%L', new Date(end)),
      request_id: uuidv4(),
      is_cold: 'static' in env,
      result: func_res,
      environment: env
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



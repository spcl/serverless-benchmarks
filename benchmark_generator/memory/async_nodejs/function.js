//#test
var config = {
  "size_in_bytes": 10485760
};
var result = {};
var number = 0;
//#import
var math = require('mathjs');
//#function
const testMemory = async (size) => {
  var t0 = new Date();
  var a = math.ones([size / 8]);
  var t1 = new Date();
  return {
    "time": t1 - t0,
    "size_in_bytes": size
  }
};
//#run
var array_size_in_bytes = config["size_in_bytes"];
await testMemory(array_size_in_bytes).then(returnJson => {
    result[number] = returnJson;
  }
);

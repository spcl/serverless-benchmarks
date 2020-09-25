//#test
var config = {
  "duration": 100
};
var result = {};
var number = 0;
//#import
//#function
const sleep = async time => {
  setTimeout(() => {}, time * 1000)   // ms to s
  return {
    "sleep_time": time
  }
};
//#run
var sleep_time = config["duration"];
await sleep(sleep_time).then(resJson => {result[number] = resJson});

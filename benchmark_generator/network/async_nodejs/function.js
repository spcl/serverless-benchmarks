//#test
var result = {};
var number = 0;
//#import
var rewire = require('rewire');
var speedTest = rewire('speedtest-net');
speedTest.__set__("__dirname", "/tmp")      // must for AWS, since only /tmp is not read-only and lib is trying to save data in __dirname
//#function
const testNetwork = async () => {
  var resultJson = {}
  try {
    await speedTest(options = {acceptLicense : true, acceptGdpr: true}).then(res => {
    //   resultJson["download"] = res.download.bandwidth;
    //   resultJson["upload"] = res.upload.bandwidth
    })
  } catch (exception) {
    resultJson["error"] = exception.toString()
  }
  return resultJson
};
//#run
await testNetwork().then(returnJson => {
    result[number] = returnJson;
  }
)

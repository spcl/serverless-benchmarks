//#test
var result = {};
var config = {
    "entries_number": 1000
};
var number = 0;
//#import
var fs = require('fs');
var uuid = require('uuid');
var uuidv1 = uuid.v1;
//#function
function generate_data(entries_number) {
    var dictToFill = {};
    for(var i = 0;i < entries_number;i++) {
        dictToFill[uuidv1()] = uuidv1()
    }
    return dictToFill
}
async function testDisc(entries_number) {
    try {
        var data = generate_data(entries_number);
        var path = "/tmp/serverless-benchmark-test-file.json";
        var dataAsString = JSON.stringify(data);
        var t0 = new Date();
        fs.writeFile(path, dataAsString)
        var t1 = new Date();
        fs.readFile(path)
        var t2 = new Date()
        return { 
            "write_time" : t1 - t0,
            "read_time": t2 - t1,
            "bytes": dataAsString.length
        }
    } catch (error) {
        return { "error": error.toString() }
    }
};
//#run
var entries_number = config.entries_number;
await testDisc(entries_number).then(returnJson => {
    result[number] = returnJson;
  }
);
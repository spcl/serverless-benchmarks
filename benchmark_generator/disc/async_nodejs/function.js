//#test
var result = {};
var config = {
    "block_size": 1024*1024*128
};
var number = 0;
//#import
var fs = require('fs');
var uuid = require('uuid');
var uuidv1 = uuid.v1;
//#function
function generate_data_disc(block_size) {
    return Array(block_size + 1).join('x')
}
async function testDisc(block_size) {
    try {
        var data = generate_data_disc(entries_number);
        var path = "/tmp/serverless-benchmark-test-file.json";
        var t0 = new Date();
        fs.writeFileSync(path, data);
        var t1 = new Date();
        await fs.readFile(path);
        var t2 = new Date();
        return { 
            "write_time" : t1 - t0,
            "read_time": t2 - t1,
            "bytes": block_size
        }
    } catch (error) {
        return { "error": error.toString() }
    }
};
//#run
var block_size = config.block_size;
await testDisc(block_size).then(returnJson => {
    result[number] = returnJson;
  }
);
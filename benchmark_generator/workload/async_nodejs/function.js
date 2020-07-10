//#test
var config = {
  "iterations": 10000,
  "operator": "-",
  "array_size": 10000
};
var result = {};
var number = 0;
//#import
var math = require('mathjs');
//#function
const performCalculations = async (iterations, operator, array_size) => {
  let scope = {
    a : math.ones([array_size]),
    b : math.ones([array_size])
  };
  var t0 = new Date(); 
  for (var i = 0; i < iterations;i++) {
    var c = math.evaluate("a " + operator + " b", scope);
  }
  var t1 = new Date();
  return {
    "number_of_operations": iterations * array_size,
    "dtype": "float64",
    "time": t1 - t0
  }
};
//#run
var iterations = config["iterations"];
var operator = config["operator"];
var array_size = config["array_size"];
await performCalculations(iterations, operator, array_size).then(returnJson => {
    result[number] = returnJson;
  }
);
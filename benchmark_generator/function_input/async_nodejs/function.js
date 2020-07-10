//#test
var config = {
    "output_size": 100
};
var result = {};
//#import
var uuid = require('uuid');
var uuidv1 = uuid.v1;
//#function
function fillDict(dictToFill, entries_number) {
    try {
        for(var i = 0;i < entries_number;i++) {
            dictToFill[uuidv1().toString()] = uuidv1().toString()
        }
        return dictToFill
    } catch (error) {
        return {"Error": error.toString}
    } 
}       
//#run
var number_of_entries = config["output_size"];
fillDict(result, number_of_entries);
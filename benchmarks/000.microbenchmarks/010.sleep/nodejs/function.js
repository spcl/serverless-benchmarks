const timer = ms => new Promise( res => setTimeout(res, ms));

exports.handler = async function(event) {
  var sleep =  event.sleep;
  return timer(sleep*1000);
};

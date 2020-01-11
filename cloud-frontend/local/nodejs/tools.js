
exports.get_config = function () {
  return {
    name: 'nodejs',
    version: process.version,
    modules: process.moduleLoadList
  };
}



DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
# Baremetal servers
cp -R $(pwd)/sebs-build/install/pypapi "${DIR}/python/"
docker build -f Dockerfile.python -t sebs-local-python "${DIR}/python"
rm -rf "${DIR}/python/pypapi"

docker build -f Dockerfile.nodejs -t sebs-local-nodejs "${DIR}/nodejs"

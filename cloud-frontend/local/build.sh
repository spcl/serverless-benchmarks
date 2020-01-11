

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
# Baremetal servers
cp -R $(pwd)/sebs-build/install/pypapi "${DIR}"
docker build -f ${DIR}/Dockerfile.python -t sebs-local-python "${DIR}"
rm -rf "${DIR}/pypapi"

docker build -f ${DIR}/Dockerfile.nodejs -t sebs-local-nodejs "${DIR}"


DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
# Baremetal servers
docker build -f "${DIR}/docker/baremetal/python/Dockerfile" -t sebs-local-python "${DIR}/docker/baremetal/python"

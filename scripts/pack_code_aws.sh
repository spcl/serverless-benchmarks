#!/bin/bash

usage() { echo "Usage: $0 [-b <benchmark_dir>] [-l <python|nodejs|cpp>]" 1>&    2; exit 1; }
while getopts ":b:l:v" o; do
  case "${o}" in
    b)
      b=${OPTARG}
      ;;
    l)
      l=${OPTARG}
      ((l == "python" || l == "nodejs" || l == "cpp")) || usage
      ;;
    v)
      VERBOSE=true
      ;;
    *)
      usage
      ;;
  esac
done
shift $((OPTIND-1))
if [ -z "${b}" ] || [ -z "${l}" ]; then
  usage
  exit
fi
# relative path to an absolute one
DIR=$(readlink -f $b)
if [ ! -d "${DIR}" ]; then
  echo "Benchmark directory ${DIR} does not exist!"
  exist
fi

logging() {
  if [ "$VERBOSE" = true ]; then
    echo $1
  fi 
}

APP_NAME=$(basename "${DIR}")
DIR="${DIR}/${l}"
REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_DIR="$(dirname ${REPO_DIR})"

# Update, Recursive, Quiet, Junk (skip relative pathnames)
CUR_DIR=$(pwd)
rm -f ${APP_NAME}.zip
zip -qrj ${APP_NAME}.zip ${DIR}/*.py ${DIR}/requirements.txt
logging "Run zip -qurj ${APP_NAME}.zip ${DIR}/*.py ${DIR}/requirements.txt"

# Install PIP packages, if required
if [ -f ${DIR}/requirements.txt ]; then
  # Install PIP packages and pack
  # Workaround for Ubuntu - --user options is provided by default
  # and clashses with target
  # https://github.com/pypa/pip/issues/3826
  pip3 -q install -r ${DIR}/requirements.txt --system -t .packages
  pushd .packages > /dev/null
  # Update, Recursive, Quiet
  zip -qr ${CUR_DIR}/${APP_NAME}.zip *
  popd > /dev/null
  rm -rf .packages
fi
logging "Created code ZIP ${APP_NAME}.zip"

# Add additional binaries, if required
if [ -f ${DIR}/init.sh ]; then
  /bin/bash ${DIR}/init.sh $(pwd)/${APP_NAME}.zip $VERBOSE
fi

zip -qurj ${APP_NAME}.zip "${REPO_DIR}/cloud-frontend/aws/python/handler.py" "${REPO_DIR}/cloud-frontend/aws/python/storage.py"
logging "Add AWS framework code to ${APP_NAME}.zip"

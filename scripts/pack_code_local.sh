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
  exit
fi

logging() {
  if [ "$VERBOSE" = true ]; then
    echo $1
  fi 
}

APP_NAME=$(basename "${DIR}")
DIR="${DIR}/${l}"
DOCKER_IMG="sebs-local-${l}"
REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_DIR="$(dirname ${REPO_DIR})"

# Find if we have to build a custom Docker image
if [ -f ${DIR}/Dockerfile ]; then
  echo "Locate specific Docker image ${DOCKER_IMG}-${APP_NAME}"
  if [ -z "$(docker images -q "${DOCKER_IMG}-${APP_NAME}")" ]; then
    echo "Rebuild image ${DOCKER_IMG}-${APP_NAME}"
    TEMP_DIR=".dockerfile_tmp"
    mkdir ${TEMP_DIR}
    pushd ${TEMP_DIR} > /dev/null
    touch Dockerfile
    echo "FROM ${DOCKER_IMG}" >> Dockerfile
    cat ${DIR}/Dockerfile >> Dockerfile
    echo "CMD [\"/bin/sh\", \"init.sh\"]" >> Dockerfile
    docker build -t "${DOCKER_IMG}-${APP_NAME}" . > /dev/null
    popd > /dev/null
    rm -rf ${TEMP_DIR}
  else
    echo "Found image ${DOCKER_IMG}-${APP_NAME}"
  fi
fi

# Update, Recursive, Quiet, Junk (skip relative pathnames)
CUR_DIR=$(pwd)
rm -f ${APP_NAME}.zip
if [ ${l} == "python" ]; then
  zip -qurj ${APP_NAME}.zip ${DIR}/*.py ${DIR}/requirements.txt
  logging "Run zip -qurj ${APP_NAME}.zip ${DIR}/*.py ${DIR}/requirements.txt"
fi
if [ ${l} == "nodejs" ]; then
  zip -qurj ${APP_NAME}.zip ${DIR}/*.js ${DIR}/package.json
  logging "Run zip -qurj ${APP_NAME}.zip ${DIR}/*.js ${DIR}/package.json"
fi

if [ ${l} == "python" ]; then
  # Install PIP packages, if required
  if [ -f ${DIR}/requirements.txt ]; then
    cp ${DIR}/requirements.txt .
    # TODO: make it dependent on config
    docker run --rm -v $(pwd):/mnt/function -e APP=${APP_NAME} sebs.build.local.python.3.6
  fi
  echo "Created code ZIP ${APP_NAME}.zip"
elif [ ${l} == "nodejs" ]; then
  if [ -f ${DIR}/package.json ]; then
    cp ${DIR}/package.json .
    # TODO: make it dependent on config
    echo "Run Docker"
    docker run --rm -v $(pwd):/mnt/function -e APP=${APP_NAME} sebs.build.local.nodejs.13.6
  fi
  echo "Created code ZIP ${APP_NAME}.zip"
fi

# Add additional binaries, if required
if [ -f ${DIR}/init.sh ]; then
  /bin/bash ${DIR}/init.sh $(pwd)/${APP_NAME}.zip $VERBOSE
fi

# There's seems to be no other way to create ZIP file
# with directories input/{file}
if [ -f ${DIR}/input.txt ]; then
    TEMP_DIR=".input"
    mkdir ${TEMP_DIR}
    pushd ${TEMP_DIR} > /dev/null

    # Create symlink for each expected file or directory
    IFS=''
    while read p; do
       for f in ${REPO_DIR}/${p}; do
         ln -s $f $(basename $f);
       done 
    done < ${DIR}/input.txt
    zip -qr ${APP_NAME}_input.zip *
    popd > /dev/null
    mv ${TEMP_DIR}/${APP_NAME}_input.zip .
    rm -rf ${TEMP_DIR}
    echo "Created data ZIP ${APP_NAME}_input.zip"
fi

# Some dependencies have broken wheels
# For example, pandas wheel for 3.10 and arm ships libraries
# for all Linux versions and all Python versions
# This is too much for Lambda

PACKAGE_DIR=$1
echo "Original size $(du -sh $1 | cut -f1)"

CUR_DIR=$(pwd)
cd $1

# remove libraries for musl
find . -name "*aarch64-linux-musl.so" | xargs rm

version=$(echo "${PYTHON_VERSION}" | sed 's/\.//g')
echo "versions ${PYTHON_VERSION} ${version}"
# remove libraries for other Python versions
find . -name "*aarch64-linux-gnu.so" | grep -v ${version} | xargs rm

cd ${CUR_DIR}
echo "Stripped size $(du -sh $1 | cut -f1)"

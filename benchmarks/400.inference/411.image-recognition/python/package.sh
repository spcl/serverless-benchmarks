# Stripping package code is based on https://github.com/ryfeus/lambda-packs repo

PACKAGE_DIR=$1
echo "Original size $(du -sh $1 | cut -f1)"

CUR_DIR=$(pwd)
cd $1
# cleaning libs
rm -rf external
find . -type d -name "tests" -exec rm -rf {} +
find . -type d -name "test" -exec rm -rf {} +
find . -type d -name "bin" -not -path "*/torch/*" -exec rm -rf {} +

# cleaning
find -name "*.so" -not -path "*/PIL/*" -not -path "*/Pillow.libs/*" | xargs strip
find -name "*.so.*" -not -path "*/PIL/*" -not -path "*/Pillow.libs/*" | xargs strip

rm -r pip > /dev/null
rm -r pip-* > /dev/null
rm -r wheel > /dev/null
rm -r wheel-* > /dev/null
rm easy_install.py > /dev/null
find . -name \*.pyc -delete
cd ${CUR_DIR}
echo "Stripped size $(du -sh $1 | cut -f1)"

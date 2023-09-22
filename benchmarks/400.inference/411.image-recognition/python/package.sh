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
# stripping some of the numpy libs - libgfortran-2e0d59d6.so.5.0.0 - causes issues on Azure
find -name "*.so" -not -path "*/PIL/*" -not -path "*/Pillow.libs/*" -not -path "*libgfortran*" | xargs strip
find -name "*.so.*" -not -path "*/PIL/*" -not -path "*/Pillow.libs/*" -not -path "*libgfortran*" | xargs strip

rm -r pip >/dev/null
rm -r pip-* >/dev/null
rm -r wheel >/dev/null
rm -r wheel-* >/dev/null
rm easy_install.py >/dev/null
find . -name \*.pyc -delete
cd ${CUR_DIR}
echo "Stripped size $(du -sh $1 | cut -f1)"

if ([[ "${PLATFORM}" == "AWS" ]] || [[ "${PLATFORM}" == "GCP" ]]) && ([[ "${PYTHON_VERSION}" == "3.8" ]] || [[ "${PYTHON_VERSION}" == "3.9" ]]); then
	zip -qr torch.zip $1/torch
	rm -rf $1/torch
	echo "Torch-zipped size $(du -sh ${CUR_DIR} | cut -f1)"
fi

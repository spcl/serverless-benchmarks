SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
CUR_DIR=$(pwd)
cd ${SCRIPT_DIR}

for C_FILE in $(ls *.c)
do
    cc -fPIC -shared -o ${C_FILE%%.*}.so ${C_FILE}
    rm ${C_FILE}
done

cd ${CUR_DIR}

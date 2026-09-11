SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
CUR_DIR=$(pwd)
cd ${SCRIPT_DIR}

for C_FILE in $(ls *.c 2>/dev/null)
do
    SO_FILE="${C_FILE%%.*}.so"
    if command -v cc &>/dev/null; then
        if cc -fPIC -shared -o ${SO_FILE} ${C_FILE}; then
            rm ${C_FILE}
        else
            echo "ERROR: Failed to compile ${C_FILE}" >&2
            exit 1
        fi
    elif [ -f "${SO_FILE}" ]; then
        # Pre-compiled .so is present; remove source to avoid confusion
        rm ${C_FILE}
    else
        echo "ERROR: No C compiler found and no pre-compiled ${SO_FILE} available" >&2
        exit 1
    fi
done

cd ${CUR_DIR}

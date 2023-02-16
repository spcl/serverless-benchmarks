#!/bin/bash

cd /mnt/function\
  && if test -f "requirements.txt.${PYTHON_VERSION}"; then pip3 -q install -r requirements.txt -r requirements.txt.${PYTHON_VERSION} -t .python_packages/lib/site-packages ; else pip3 -q install -r requirements.txt -t .python_packages/lib/site-packages ; fi\
  && if test -f "${SCRIPT_FILE}"; then /bin/bash ${SCRIPT_FILE} .python_packages/lib/site-packages ; fi

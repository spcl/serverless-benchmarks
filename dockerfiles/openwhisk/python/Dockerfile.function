ARG BASE_IMAGE
FROM $BASE_IMAGE
ARG VERSION
ENV PYTHON_VERSION=${VERSION}
COPY . function/

RUN touch function/__init__.py \
    && if test -f "function/requirements.txt.${PYTHON_VERSION}"; then pip install --no-cache-dir -r function/requirements.txt -r function/requirements.txt.${PYTHON_VERSION} function/ ; else pip install --no-cache-dir -r function/requirements.txt function/ ; fi


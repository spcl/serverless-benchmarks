# Linux ARM64 and x86_64 builds for vLLM 0.31.0, with CPU-only inference.

######################### BASE STAGE #########################
FROM ubuntu:24.04 AS base-common

ARG PYTHON_VERSION=3.12.15
ARG VERSION=3.12
ARG UV_VERSION=0.13.1
ARG PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /workspace

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        ccache git curl wget ca-certificates \
        gcc-12 g++-12 make libtcmalloc-minimal4 libnuma-dev libgomp1 \
        ffmpeg libsm6 libxext6 libgl1 jq lsof && \
    update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 10 \
        --slave /usr/bin/g++ g++ /usr/bin/g++-12 && \
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | env UV_INSTALL_DIR=/usr/local/bin sh

# Keep the managed interpreter outside /root so Lambda's runtime user can use it.
# Both build and runtime inherit this same interpreter layer.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    VIRTUAL_ENV=/opt/venv \
    UV_HTTP_TIMEOUT=500 \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    UV_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    UV_INDEX_STRATEGY=unsafe-best-match \
    UV_LINK_MODE=copy

RUN uv venv --python "${PYTHON_VERSION}" --managed-python --seed "${VIRTUAL_ENV}" \
    && chmod -R a+rX /opt/uv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

######################### CPU BASE #########################
FROM base-common AS base-cpu
RUN mkdir -p /opt/sebs/lib \
    && ln -s "/usr/lib/$(gcc -print-multiarch)/libtcmalloc_minimal.so.4" \
        /opt/sebs/lib/libtcmalloc_minimal.so.4
ENV LD_PRELOAD=/opt/sebs/lib/libtcmalloc_minimal.so.4

######################### DEPENDENCIES #########################
FROM base-cpu AS dependencies
COPY requirements.txt.*.lock /opt/sebs/
RUN case "$(uname -m)" in \
        aarch64) lock=arm64 ;; \
        x86_64) lock=x64 ;; \
        *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;; \
    esac \
    && cp "/opt/sebs/requirements.txt.${lock}.lock" /opt/sebs/requirements.lock \
    && python3 -m pip install --require-hashes --no-deps --only-binary=:all: \
        -r /opt/sebs/requirements.lock \
    && python3 -m pip check

######################### BUILD STAGE #########################
FROM dependencies AS vllm-build

ARG VLLM_VERSION=0.31.0
ARG MAX_JOBS=4

ENV VLLM_TARGET_DEVICE=cpu \
    MAX_JOBS=${MAX_JOBS} \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAX_JOBS} \
    CCACHE_DIR=/root/.cache/ccache \
    UV_CACHE_DIR=/root/.cache/uv

WORKDIR /workspace
RUN git clone --depth 1 --branch "v${VLLM_VERSION}" \
        https://github.com/vllm-project/vllm.git /workspace/vllm

WORKDIR /workspace/vllm

COPY patches/ /opt/sebs/patches/
RUN git apply --check /opt/sebs/patches/vllm-0.31.0-uniproc.patch \
    && git apply /opt/sebs/patches/vllm-0.31.0-uniproc.patch \
    && git apply --check /opt/sebs/patches/vllm-0.31.0-cpu-topology.patch \
    && git apply /opt/sebs/patches/vllm-0.31.0-cpu-topology.patch

RUN git apply --check /opt/sebs/patches/vllm-0.31.0-l2-cache.patch \
    && git apply /opt/sebs/patches/vllm-0.31.0-l2-cache.patch

# Use the exact dependency used in vLLM 0.31.0.
ARG ACL_COMMIT=007264fa740de5723ebddef16b7bb3657692c088
ARG ONEDNN_ARM64_COMMIT=9c5be1cc59e368aebf0909e6cf20f981ea61462a
ARG ONEDNN_X64_COMMIT=0e2a5bfeef1bfbffc3137464606540233086ce9b
RUN mkdir -p /workspace/acl /workspace/onednn \
    && case "$(uname -m)" in \
        aarch64) \
            onednn_commit="${ONEDNN_ARM64_COMMIT}"; \
            curl --fail --location --retry 5 \
                "https://codeload.github.com/ARM-software/ComputeLibrary/tar.gz/${ACL_COMMIT}" \
                -o /tmp/acl.tar.gz \
            && tar -xzf /tmp/acl.tar.gz -C /workspace/acl --strip-components=1 \
            && rm /tmp/acl.tar.gz ;; \
        x86_64) onednn_commit="${ONEDNN_X64_COMMIT}" ;; \
        *) exit 1 ;; \
    esac \
    && curl --fail --location --retry 5 \
        "https://codeload.github.com/uxlfoundation/oneDNN/tar.gz/${onednn_commit}" \
        -o /tmp/onednn.tar.gz \
    && tar -xzf /tmp/onednn.tar.gz -C /workspace/onednn --strip-components=1 \
    && rm /tmp/onednn.tar.gz

RUN if [ "$(uname -m)" = "aarch64" ]; then \
        cd /workspace/onednn \
        && git apply --check /opt/sebs/patches/onednn-arm64-midr.patch \
        && git apply /opt/sebs/patches/onednn-arm64-midr.patch; \
    fi

ENV ACL_ROOT_DIR=/workspace/acl \
    FETCHCONTENT_SOURCE_DIR_ONEDNN=/workspace/onednn

RUN SETUPTOOLS_SCM_PRETEND_VERSION="${VLLM_VERSION}" \
        python3 setup.py bdist_wheel --dist-dir=dist

# Collect ACL shared libraries if this build produces them.
RUN mkdir -p /workspace/arm_compute_libs \
    && if [ -d /workspace/vllm/.deps ]; then \
        find -L /workspace/vllm/.deps -type f -name 'libarm_compute*.so*' \
            -exec cp -L -t /workspace/arm_compute_libs/ {} +; \
    fi

######################### RUNTIME STAGE #########################
FROM base-cpu AS runtime

WORKDIR /var/task

ENV VLLM_TARGET_DEVICE=cpu \
    VLLM_CPU_OMP_THREADS_BIND=all \
    VLLM_ENABLE_V1_MULTIPROCESSING=0 \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config \
    XDG_DATA_HOME=/tmp/.local/share \
    PYTHONDONTWRITEBYTECODE=1 \
    LD_LIBRARY_PATH=/opt/sebs/lib:/opt/venv/lib

COPY --from=vllm-build /opt/venv/ /opt/venv/
COPY --from=vllm-build /workspace/arm_compute_libs/ /opt/sebs/lib/
COPY --from=vllm-build /opt/sebs/requirements.lock /opt/sebs/requirements.lock
RUN ldconfig

# Install only our local vLLM wheel, without resolving.
COPY --from=vllm-build /workspace/vllm/dist/ /tmp/dist/
RUN python3 -m pip install --no-deps /tmp/dist/*.whl \
    && python3 -m pip check

######################### LAMBDA FUNCTION #########################
# SeBS supplies handler.py and storage.py in the build context.
COPY . /var/task/function/
RUN touch /var/task/function/__init__.py \
    && chmod -R a+rX /var/task/function

ENTRYPOINT ["/opt/venv/bin/python3", "-m", "awslambdaric"]
CMD ["function.handler.handler"]

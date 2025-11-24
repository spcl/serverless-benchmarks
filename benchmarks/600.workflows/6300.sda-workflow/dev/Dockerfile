# Define custom base image
ARG BASE_IMAGE="python:3.12"

FROM ${BASE_IMAGE} AS build-image
RUN apt-get update && apt-get install -y python3-pip

# Include global arg in this stage of the build
ARG LAMBDA_DIR="/lambda"

# Copy function code
RUN mkdir -p ${LAMBDA_DIR}
RUN mkdir -p ${LAMBDA_DIR}/function
COPY . ${LAMBDA_DIR}/function

# Install the function's dependencies
RUN pip install \
    --target ${LAMBDA_DIR} \
        awslambdaric
WORKDIR ${LAMBDA_DIR}
# Set runtime interface client as default command for the container runtime
ENTRYPOINT [ "/usr/bin/python", "-m", "awslambdaric" ]
# Pass the name of the function handler as an argument to the runtime
CMD [ "function/handler.handler" ]
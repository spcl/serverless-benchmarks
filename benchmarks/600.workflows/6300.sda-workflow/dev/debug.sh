#!/bin/bash
if [ -n "$(docker ps -aq -f name=^sda-aws-container$)" ]; then
    echo "Removing existing container sda-aws-container..."
    docker rm -f sda-aws-container >/dev/null 2>&1 || true
fi
WORKFLOW_NAME="SDA"
FUNCTION="filter"
docker run --platform linux/amd64 -d -v ~/.aws-lambda-rie:/aws-lambda -v /home/lolo/Projects/serverless-benchmarks/benchmarks/600.workflows/6300.sda-workflow/dev/data:/data -p 9000:8080 -e AWS_LAMBDA_FUNCTION_NAME=${WORKFLOW_NAME}___${FUNCTION} --entrypoint /aws-lambda/aws-lambda-rie --name sda-aws-container logru/sda-sebs-aws:latest /usr/bin/python -m awslambdaric function/handler.handler 
docker exec -it sda-aws-container /bin/bash
docker rm -f sda-aws-container >/dev/null 2>&1 || true
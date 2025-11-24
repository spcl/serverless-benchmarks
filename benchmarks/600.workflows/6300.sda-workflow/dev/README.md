# Docker Commands:
### Build Image
```
docker build  \
--build-arg BASE_IMAGE=logru/sda:latest \
-t logru/sda-sebs-aws \
-f benchmarks/600.workflows/6300.sda-workflow/dev/Dockerfile \
6300.sda-workflow_code/python/3.8/x64/package/
```
### Test Run
[Custom Image Tutorial](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html#python-image-clients)
#### Start Container
```
docker run \
--platform linux/amd64 -d \
-v ~/.aws-lambda-rie:/aws-lambda \
-p 9000:8080 \
-e AWS_LAMBDA_FUNCTION_NAME=SDA___filter \
--entrypoint /aws-lambda/aws-lambda-rie \
--name sda-aws-container \
logru/sda-sebs-aws:latest \
/usr/bin/python -m awslambdaric function/handler.handler 
``` 
#### Debug Container
```
docker exec -it sda-aws-container /bin/bash
```
#### Trigger Requests
```
curl "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"payload":{},"request_id":"1"}'
```

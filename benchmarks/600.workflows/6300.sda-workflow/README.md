# Docker Commands:
### Build Image
```
docker build  -t sebs/sda-aws -f  dockerfiles/aws/python/Dockerfile.base 6300.sda-workflow_code/python/3.8/x64/container/function/build/
```
### Test Run
[Custom Image Tutorial](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html#python-image-clients)
#### Start Container
```
docker run \
--platform linux/amd64 -d \
-v ~/.aws-lambda-rie:/aws-lambda \
-p 9000:8080 \
--entrypoint /aws-lambda/aws-lambda-rie \
--name sda-aws-container \
logru/sda-aws:latest \
/usr/bin/python -m awslambdaric function/handler.handler 
``` 
#### Debug Container
```
docker exec -it sda-aws-container /bin/bash
```
#### Trigger Requests
```
 curl "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{}'
```

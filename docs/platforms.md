
SeBS supports three commercial serverless platforms: AWS Lambda, Azure Functions, and Google Cloud Functions.
Furthermore, we support the open source FaaS system OpenWhisk.

The file `config/example.json` contains all parameters that users can change
to customize the deployment.
Some of these parameters, such as cloud credentials or storage instance address,
are required.
In the following subsections, we discuss the mandatory and optional customization
points for each platform.

## AWS Lambda

AWS provides one year of free services, including a significant amount of computing time in AWS Lambda.
To work with AWS, you need to provide access and secret keys with permissions
sufficient to manage functions, S3 resources.
When working with communication benchmarks, it might be necessary to use DynamoDB as well.
Additionally, the account must have `AmazonAPIGatewayAdministrator` permission to set up
automatically AWS HTTP trigger.

You can provide a [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
with permissions to access AWS Lambda and S3; otherwise, one will be created automatically.
To run communication benchmarks, the role needs to access DynamoDB.
Furthermore, to access AWS ElastiCache, the role needs an additional permission:
`AWSLambdaVPCAccessExecutionRole`.
To use a user-defined lambda role, set the name in config JSON - see an example in `config/example.json`.

**Pass the credentials as environmental variables for the first run.** They will be cached for future use.

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

## Azure Functions

Azure provides a free tier for 12 months.
You need to create an account and add a [service principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal)
to enable non-interactive login through CLI.
Since this process has [an easy, one-step CLI solution](https://docs.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest#az-ad-sp-create-for-rbac),
we added a small tool **tools/create_azure_credentials** that uses the interactive web-browser
authentication to login into Azure CLI and create a service principal.

```console
Please provide the intended principal name                                                                                                         
XXXXX
Please follow the login instructions to generate credentials...                                                            
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code YYYYYYY to authenticate.

Login succesfull with user {'name': 'ZZZZZZ', 'type': 'user'}                                          
Created service principal http://XXXXX

AZURE_SECRET_APPLICATION_ID = XXXXXXXXXXXXXXXX
AZURE_SECRET_TENANT = XXXXXXXXXXXX
AZURE_SECRET_PASSWORD = XXXXXXXXXXXXX
```

**Save these credentials - the password is non-retrievable! Provide them to SeBS through environmental variables**,
and we will create additional resources (storage account, resource group) to deploy functions.
We will create a storage account and the resource group and handle access keys.

### Resources

* By default, all functions are allocated in the single resource group.
* Each function has a seperate storage account allocated, following [Azure guidelines](https://docs.microsoft.com/en-us/azure/azure-functions/functions-best-practices#scalability-best-practices).
* All benchmark data is stored in the same storage account.

## Google Cloud Functions

The Google Cloud Free Tier gives free resources. It has two parts:

- A 12-month free trial with $300 credit to use with any Google Cloud services.
- Always Free, which provides limited access to many common Google Cloud resources, free of charge.

You need to create an account and add [service account](https://cloud.google.com/iam/docs/service-accounts) to permit operating on storage and functions.
You have two options to pass the credentials to SeBS:

- specify the project name nand path to JSON credentials in the config JSON file, see an example in `config/example.json`
- use environment variables

```
export GCP_PROJECT_NAME = XXXX
export GCP_SECRET_APPLICATION_CREDENTIALS = XXXX
```

## OpenWhisk

SeBS expects users to deploy and configure an OpenWhisk instance.
In `tools/openwhisk_preparation.py`, we include scripts that help install
[kind (Kubernetes in Docker)](https://kind.sigs.k8s.io/) and deploy
OpenWhisk on a `kind` cluster.
The configuration parameters of OpenWhisk for SeBS can be found
in `config/example.json` under the key `['deployment']['openwhisk']`.
In the subsections below, we discuss the meaning and use of each parameter.
To correctly deploy SeBS functions to OpenWhisk, following the
subsections on *Toolchain* and *Docker* configuration is particularly important.

### Toolchain

We use OpenWhisk's CLI tool [wsk](https://github.com/apache/openwhisk-cli)
to manage the deployment of functions to OpenWhisk.
Please install `wsk`and configure it to point to your OpenWhisk installation.
By default, SeBS assumes that `wsk` is available in the `PATH`.
To override this, set the configuration option `wskExec` to the location
of your `wsk` executable.
If you are using a local deployment of OpenWhisk with a self-signed
certificate, you can skip certificate validation with the `wsk` flag `--insecure`.
To enable this option, set `wskBypassSecurity` to `true`.
At the moment, all functions are deployed as [*web actions*](https://github.com/apache/openwhisk/blob/master/docs/webactions.md)
that do not require credentials to invoke functions.

Furthermore, SeBS can be configured to remove the `kind`
cluster after finishing experiments automatically.
The boolean option `removeCluster` helps to automate the experiments
that should be conducted on fresh instances of the system.

### Docker

In FaaS platforms, the function's code can usually be deployed as a code package
or a Docker image with all dependencies preinstalled.
However, OpenWhisk has a very low code package size limit of only 48 megabytes.
So, to circumvent this limit, we deploy functions using pre-built Docker images.

**Important**: OpenWhisk requires that all Docker images are available
in the registry, even if they have been cached on a system serving OpenWhisk
functions.
Function invocations will fail when the image is not available after a
timeout with an error message that does not directly indicate image availability issues.
Therefore, all SeBS benchmark functions are available on the Docker Hub.

When adding new functions and extending existing functions with new languages
and new language versions, Docker images must be placed in the registry.
However, pushing the image to the default `spcleth/serverless-benchmarks`
repository on Docker Hub requires permissions.
To use a different Docker Hub repository, change the key
`['general']['docker_repository']` in `config/systems.json`.


Alternatively, OpenWhisk users can configure the FaaS platform to use a custom and
private Docker registry and push new images there.
A local Docker registry can speed up development when debugging a new function.
SeBS can use alternative Docker registry - see `dockerRegistry` settings
in the example to configure registry endpoint and credentials.
When the `registry` URL is not provided, SeBS will use Docker Hub.
When `username` and `password` are provided, SeBS will log in to the repository
and push new images before invoking functions.
See the documentation on the
[Docker registry](https://github.com/apache/openwhisk-deploy-kube/blob/master/docs/private-docker-registry.md)
and [OpenWhisk configuration](https://github.com/apache/openwhisk-deploy-kube/blob/master/docs/private-docker-registry.md)
for details.

**Warning**: this feature is experimental and has not been tested extensively.
At the moment, it cannot be used on a `kind` cluster due to issues with
Docker authorization on invoker nodes. [See the OpenWhisk issue for details](https://github.com/apache/openwhisk-deploy-kube/issues/721).

### Code Deployment

SeBS builds and deploys a new code package when constructing the local cache,
when the function's contents have changed, and when the user requests a forced rebuild.
In OpenWhisk, this setup is changed - SeBS will first attempt to verify 
if the image exists already in the registry and skip building the Docker
image when possible.
Then, SeBS can deploy seamlessly to OpenWhisk using default images
available on Docker Hub.
Furthermore, checking for image existence in the registry helps
avoid failing invocations in OpenWhisk.
For performance reasons, this check is performed only once when 
initializing the local cache for the first time.

When the function code is updated,
SeBS will build the image and push it to the registry.
Currently, the only available option of checking image existence in
the registry is pulling the image.
However, Docker's [experimental `manifest` feature](https://docs.docker.com/engine/reference/commandline/manifest/)
allows checking image status without downloading its contents, saving bandwidth and time.
To use that feature in SeBS, set the `experimentalManifest` flag to true.

### Storage 

To provide persistent object storage in OpenWhisk, users must first deploy an instance
of [`Minio`](https://github.com/minio/minio) storage.
The storage instance is deployed as a Docker container, and it can be retained
across many experiments.
OpenWhisk functions must be able to reach the storage instance.
Even on a local machine, it's necessary to configure the network address, as OpenWhisk functions
are running isolated from the host network and won't be able to reach other containers running on the Docker bridge.

Use the following command to deploy the storage instance locally and map the host public port 9011 to Minio instance.

```bash
./sebs.py storage start minio --port 9011 --output-json out_storage.json
```

The output will look similar to the one below.
As we can see, the storage container is running on the default Docker bridge network with address `172.17.0.2` and uses port `9000`.
From the host network, port `9011` is mapped to the container's port `9000` to allow external parties - such as OpenWhisk functions - to reach the storage.

```
{
  "address": "172.17.0.2:9000",
  "mapped_port": 9011,
  "access_key": "XXX",
  "secret_key": "XXX",
  "instance_id": "XXX",
  "input_buckets": [],
  "output_buckets": [],
  "type": "minio"
}
```

The storage configuration found in `out_storage.json` needs to be provided to SeBS,
and the instance address must be updated to not use the internal address.
In this case, the host machine's address is `172.22.20.30`.
Note that that other parties must use the host network port `9011` to reach Minio instance.
Docker's port mapping will take care of the rest.

```
jq --argfile file1 out_storage.json '.deployment.openwhisk.storage = $file1, .deployment.openwhisk.storage.address = 172.22.20.30:9011' config/example.json > config/openwhisk.json
```

Not sure which address is correct? Use `curl` to verify if Minio's instance can be reached:

```
curl -i 172.22.20.30:9011/minio/health/live
HTTP/1.1 200 OK
Accept-Ranges: bytes
Content-Length: 0
Content-Security-Policy: block-all-mixed-content
Server: MinIO
Strict-Transport-Security: max-age=31536000; includeSubDomains
Vary: Origin
X-Amz-Request-Id: 16F3D9B9FDFFA340
X-Content-Type-Options: nosniff
X-Xss-Protection: 1; mode=block
Date: Mon, 30 May 2022 10:01:21 GMT
```

The `shutdownStorage` switch controls the behavior of SeBS.
When set to true, SeBS will remove the Minio instance after finishing all 
work.
Otherwise, the container will be retained, and future experiments with SeBS
will automatically detect an existing Minio instance.
Reusing the Minio instance helps run experiments faster and smoothly since
SeBS does not have to re-upload function's data on each experiment.


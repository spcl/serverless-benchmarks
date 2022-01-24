
SeBS supports three commercial serverless platforms: AWS Lambda, Azure Functions, and Google Cloud
Functions.
Furthermore, we support the open source FaaS system OpenWhisk.

## AWS Lambda

AWS provides one year of free services, including a significant amount of computing time in AWS Lambda.
To work with AWS, you need to provide access and secret keys to a role with permissions
sufficient to manage functions and S3 resources.
Additionally, the account must have `AmazonAPIGatewayAdministrator` permission to set up
automatically AWS HTTP trigger.
You can provide a [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
with permissions to access AWS Lambda and S3; otherwise, one will be created automatically.
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

SeBS expects users have to deploy and configure OpenWhisk instance.
In `tools/openwhisk_preparation.py`, we include scripts that help to install
[kind (Kubernetes in Docker)](https://kind.sigs.k8s.io/) and deploy
OpenWhisk on a `kind` cluster.
An example of SeBS configuration for using OpenWhisk can be found in `config/example.json`
under the key `['deployment']['openwhisk']`.
In subsections below, we discuss the meaning and use of each parameter.
To correctly deploy SeBS functions to OpenWhisk, it is important to follow the
subsections on *Toolchain* and *Docker* configuration.

### Toolchain

We use OpenWhisk's CLI tool [wsk](https://github.com/apache/openwhisk-cli)
to manage the deployment of functions to OpenWhisk.
To deploy serverless functions, please install `wsk` and
configure it to point to your OpenWhisk installation.
By default, SeBS assumes that `wsk` is available in the `PATH`.
To override this, set the configuration option `wskExec` to the location
of your `wsk` executable.
If you are using a local deployment of OpenWhisk with a self-signed
certificate, you can skip certificate validation with the `wsk` flag `--insecure`.
To enable this option, set `wskBypassSecurity` to `true`.
At the moment, all functions are deployed as [*web actions*](https://github.com/apache/openwhisk/blob/master/docs/webactions.md)
that do not require using credentails to invoke functions.

Furthermore, SeBS can be configured to automatically remove the `kind`
cluster after finishing experiments. This helps to automate the experiments
that should be conducted on fresh instances of the system.
To enable this option, set `removeCluster` to `true`.

### Docker

In FaaS platforms, function's code can be usually deployed as a code package
or as a Docker image with all dependencies preinstalled.
However, OpenWhisk as a very low limit on the code package size of only 48
megabytes.
To circumvent this limit, we deploy functions using pre-built Docker images.

**Important**: OpenWhisk requires that all Docker images are available
in the registry, even if they have been cached on a system serving OpenWhisk
functions.
When the image is not available, function invocations will fail after a timeout
with an error message that does not indicate directly image availability issues.
All SeBS benchmark functions are available on the Docker Hub.

When adding new functions and extending existing functions with new languages
and new language versions, Docker images must be placed in the registry.
However, pushin the image to `spcleth/serverless-benchmarks` repository on Docker
Hub requires permissions.
Instead, OpenWhisk users can configure the FaaS platform to use a custom and
private Docker registry and push new images there.
Furthermore, a local Docker registry can speed up development when debugging
a new function.
See the documentation on
[Docker registry](https://github.com/apache/openwhisk-deploy-kube/blob/master/docs/private-docker-registry.md)
and [OpenWhisk configuration](https://github.com/apache/openwhisk-deploy-kube/blob/master/docs/private-docker-registry.md)
for details.
SeBS can use alternative Docker registry - see `dockerRegistry` settings
in the example to configure registry endpoint and credentials.
When `registry` URL is not provided, SeBS will use Docker Hub.
When `username` and `password` are provided, `SeBS` will use them to login
to the repository.

### Code Deployment

SeBS builds and deploys a new code package when constructing the local cache,
when function's content have change, and when user reuqests a forced rebuild.
In OpenWhisk, this set up is changed - SeBS will first attempt to verify 
if the image exists already in the registry and skip building Docker
image when possible.
This allows SeBS to deploy seamlessly to OpenWhisk using default images
available on Docker Hub.
Furthermore, checking for image existence in the registry helps
to avoid failing invocations in OpenWhisk.
For performance reasons, this check is performed only once, when constructing
the local cache.

When the function code must be updated,
SeBS will build the image and attempt to push it to the registry.
At the moment, the only available option of checking image existence in
the registry is pulling the image.
However, there is [an experimental `manifest` feature of Docker](https://docs.docker.com/engine/reference/commandline/manifest/)
that allow to check image status without downloading its contents,
saving bandwidth and time.
To use that feature in SeBS, set `experimentalManifest` flag to true.

### Storage 

To provide persistent object storage in OpenWhisk, we deploy an instance
of [`Minio`](https://github.com/minio/minio) storage.
The storage instance is deployed as a Docker container, and it can be retained
across many experiments.
The behavior of SeBS is controlled by the `shutdownStorage` switch.
When set to true, SeBS will remove Minio instance after finishing all 
work.
Otherwise, the container will be retained and future experiments with SeBS
will automatically detect an existing Minio instance.
Reusing Minio instance helps to run experiments faster and smoothly since
SeBS does not have to reupload function's inputs on each experiment.


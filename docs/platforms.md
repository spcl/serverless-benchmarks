
SeBS supports four commercial serverless platforms: AWS Lambda, Azure Functions, Google Cloud Functions, and Cloudflare Workers.
Furthermore, we support the open source FaaS system OpenWhisk.

The file `config/example.json` contains all parameters that users can change
to customize the deployment.
Some of these parameters, such as cloud credentials or storage instance address,
are required.
In the following subsections, we discuss the mandatory and optional customization
points for each platform.

> [!WARNING]
> On many platforms, credentials can be provided as environment variables or through the SeBS configuration. SeBS will not store your credentials in the cache. When saving results, SeBS stores user benchmark and experiment configuration for documentation and reproducibility, except for credentials that are erased. If you provide the credentials through JSON input configuration, do not commit nor publish these files anywhere.

Supported platforms:
* [Amazon Web Services (AWS) Lambda](#aws-lambda)
* [Microsoft Azure Functions](#azure-functions)
* [Google Cloud (GCP) Functions](#google-cloud-functions)
* [Cloudflare Workers](#cloudflare-workers)
* [OpenWhisk](#openwhisk)

## Storage Configuration

SeBS benchmarks rely on persistent object and NoSQL storage for input and output data. For configuration instructions regarding both object storage and NoSQL databases, please refer to the [storage documentation](storage.md). Storage configuration is particularly important for local deployments, OpenWhisk, and other open-source FaaS platforms.

## Architectures

By default, SeBS defaults functions built for the x64 (x86_64) architecture. On AWS, functions can also be build and deployed for ARM CPUs to benefit from Graviton CPUs available on Lambda.
This change primarily affects functions that make use of dependencies with native builds, such as `torch`, `numpy` or `ffmpeg`.

Such functions can be build as code packages on any platforms, as we rely on package managers like pip and npm to provide binary dependencies.
However, special care is needed to build Docker containers: since installation of packages is a part of the Docker build, we cannot natively execute
binaries based on ARM containers on x86 CPUs. To build multi-platform images, we recommend to follow official [Docker guidelines](https://docs.docker.com/build/building/multi-platform/#build-multi-platform-images) and provide static QEMU installation.
On Ubuntu-based distributions, this requires installing an OS package and executing a single Docker command to provide seamless emulation of ARM containers.

## Cloud Account Identifiers

SeBS ensures that all locally cached cloud resources are valid by storing a unique identifier associated with each cloud account. Furthermore, we store this identifier in experiment results to easily match results with the cloud account or subscription that was used to obtain them. We use non-sensitive identifiers such as account IDs on AWS, subscription IDs on Azure, and Google Cloud project IDs.

If you have JSON result files, such as `experiment.json` from a benchmark run or '<experiment>/*.json' from an experiment, you can remove all identifying information by removing the JSON object `.config.deployment.credentials`. This can be achieved easily with the CLI tool `jq`:

```
jq 'del(.config.deployment.credentials)' <file.json> | sponge <file.json>
```

## AWS Lambda

AWS provides one year of free services, including a significant amount of computing time in AWS Lambda.
To work with AWS, you need to provide access and secret keys to a role with permissions
sufficient to manage functions and S3 resources.
Additionally, the account must have `AmazonAPIGatewayAdministrator` permission to set up
automatically AWS HTTP trigger.
You can provide a [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
with permissions to access AWS Lambda and S3; otherwise, one will be created automatically.
To use a user-defined lambda role, set the name in config JSON - see an example in `config/example.json`.

You can pass the credentials either using the default AWS-specific environment variables:

```
export AWS_ACCESS_KEY_ID=XXXX
export AWS_SECRET_ACCESS_KEY=XXXX
```

or in the JSON input configuration:

```json
"deployment": {
  "name": "aws",
  "aws": {
    "region": "us-east-1",
    "lambda-role": "",
    "credentials": {
      "access_key": "YOUR AWS ACCESS KEY",
      "secret_key": "YOUR AWS SECRET KEY"
    }
  }
}
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

**Save these credentials - the password is non-retrievable! Provide them to SeBS and we will create additional resources (storage account, resource group) to deploy functions. We will create a storage account and the resource group and handle access keys.

You can pass the credentials either using the environment variables:

```
export AZURE_SECRET_APPLICATION_ID = XXXXXXXXXXXXXXXX
export AZURE_SECRET_TENANT = XXXXXXXXXXXX
export AZURE_SECRET_PASSWORD = XXXXXXXXXXXXX
```

or in the JSON input configuration:

```json
"deployment": {
  "name": "azure",
  "azure": {
    "region": "westeurope"
    "credentials": {
      "appID": "YOUR SECRET APPLICATION ID",
      "tenant": "YOUR SECRET TENANT",
      "password": "YOUR SECRET PASSWORD"
    }
  }
}
```

> [!WARNING]
> The tool assumes there is only one subscription active on the account. If you want to bind the newly created service principal to a specific subscription, or the created credentials do not work with SeBS and you see errors such as "No subscriptions found for X", then you must specify a subscription when creating the service principal. Check your subscription ID on in the Azure portal, and use the CLI option `tools/create_azure_credentials.py --subscription <SUBSCRIPTION_ID>`.

> [!WARNING]
> When you log in for the first time on a device, Microsoft might require authenticating your login with Multi-Factor Authentication (MFA). In this case, we will return an error such as: "The following tenants require Multi-Factor Authentication (MFA). Use 'az login --tenant TENANT_ID' to explicitly login to a tenant.". Then, you can pass the tenant ID by using the `--tenant <tenant-id>` flag.

### Resources

* By default, all functions are allocated in the single resource group.
* Each function has a separate storage account allocated, following [Azure guidelines](https://docs.microsoft.com/en-us/azure/azure-functions/functions-best-practices#scalability-best-practices).
* All benchmark data is stored in the same storage account.

## Google Cloud Functions

The Google Cloud Free Tier gives free resources. It has two parts:

- A 12-month free trial with $300 credit to use with any Google Cloud services.
- Always Free, which provides limited access to many common Google Cloud resources, free of charge.

You need to create an account and add [service account](https://cloud.google.com/iam/docs/service-accounts) to permit operating on storage and functions. From the cloud problem, download the cloud credentials saved as a JSON file.
You should have at least write access to **Cloud Functions** (`Cloud Functions Admin`) and **Logging** Furthermore, SeBS needs the permissions to create Firestore databases through
Google Cloud CLI tool; the `Firestore Service Agent` role allows for that.

You can pass the credentials either using the default GCP-specific environment variable:

```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/project-credentials.json
```

using the SeBS environment variable:

```
export GCP_SECRET_APPLICATION_CREDENTIALS=/path/to/project-credentials.json
```

or in the JSON input configuration:

```json
"deployment": {
  "name": "gcp",
  "gcp": {
    "region": "europe-west1",
    "credentials": "/path/to/project-credentials.json"
  }
}
```

## Cloudflare Workers

Cloudflare offers a free tier for Workers with generous limits for development and testing. To use Cloudflare Workers with SeBS, you need to create a Cloudflare account and obtain API credentials.

### Credentials

You can authenticate with Cloudflare using an API token (recommended) or email + API key. Additionally, you need your account ID which can be found in the Cloudflare dashboard.

You can pass credentials using environment variables:

```bash
# Option 1: Using API Token (recommended)
export CLOUDFLARE_API_TOKEN="your-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"

# Option 2: Using Email + API Key
export CLOUDFLARE_EMAIL="your-email@example.com"
export CLOUDFLARE_API_KEY="your-global-api-key"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
```

or in the JSON configuration file:

```json
"deployment": {
  "name": "cloudflare",
  "cloudflare": {
    "credentials": {
      "api_token": "your-api-token",
      "account_id": "your-account-id"
    },
    "resources": {
      "resources_id": "unique-resource-id"
    }
  }
}
```

**Note**: The `resources_id` is used to uniquely identify and track resources created by SeBS for a specific deployment.

### Language Support

Cloudflare Workers support multiple languages through different deployment methods:

- **JavaScript/Node.js**: Supported via script-based deployment or container-based deployment using Wrangler CLI
- **Python**: Supported via script-based deployment or container-based deployment using Wrangler CLI

### CLI Container

SeBS uses a containerized CLI approach for Cloudflare deployments, eliminating the need to install Node.js, npm, wrangler, pywrangler, or uv on your host system. The CLI container (`sebs/manage.cloudflare`) is automatically built on first use and contains all necessary tools. This ensures consistent behavior across platforms and simplifies setup—only Docker is required.

### Trigger Support

- **HTTP Trigger**: ✅ Fully supported - Workers are automatically accessible at `https://{name}.{account}.workers.dev`
- **Library Trigger**: ❌ Not currently supported

### Platform Limitations

- **Cold Start Detection**: Cloudflare does not expose cold start information. All invocations report `is_cold: false` in the metrics. This limitation means cold start metrics are not available for Cloudflare Workers benchmarks.
- **Memory/Timeout Configuration (Workers)**: Managed by Cloudflare (128MB memory, 30s CPU time on free tier)
- **Memory/Timeout Configuration (Containers)**: Managed by Cloudflare, available in different tiers:

  | Instance Type | vCPU | Memory | Disk |
  |---------------|------|--------|------|
  | lite | 1/16 | 256 MiB | 2 GB |
  | basic | 1/4 | 1 GiB | 4 GB |
  | standard-1 | 1/2 | 4 GiB | 8 GB |
  | standard-2 | 1 | 6 GiB | 12 GB |
  | standard-3 | 2 | 8 GiB | 16 GB |
  | standard-4 | 4 | 12 GiB | 20 GB |
- **Metrics Collection**: Uses response-based per-invocation metrics. During each function invocation, the worker handler measures performance metrics (CPU time, wall time, memory usage) and embeds them directly in the JSON response. SeBS extracts these metrics immediately from each response. When `download_metrics()` is called for postprocessing, it only aggregates the metrics that were already collected during invocations—no additional data is fetched from external services. This approach provides immediate per-invocation granularity without delays. Note that while Cloudflare does expose an Analytics Engine, it only provides aggregated metrics without individual request-level data, making it unsuitable for detailed benchmarking purposes.

### Storage Configuration

Cloudflare Workers integrate with Cloudflare R2 for object storage and Durable Objects for NoSQL storage. For detailed storage configuration, see the [storage documentation](storage.md#cloudflare-storage).

## OpenWhisk

SeBS expects users to deploy and configure an OpenWhisk instance.
Below, you will find example of instruction for deploying OpenWhisk instance.
The configuration parameters of OpenWhisk for SeBS can be found
in `config/example.json` under the key `['deployment']['openwhisk']`.
In the subsections below, we discuss the meaning and use of each parameter.
To correctly deploy SeBS functions to OpenWhisk, following the
subsections on *Toolchain* and *Docker* configuration is particularly important.

For storage configuration in OpenWhisk, refer to the [storage documentation](storage.md), which covers both object storage and NoSQL requirements specific to OpenWhisk deployments.

> [!WARNING]
> Some benchmarks might require larger memory allocations, e.g., 2048 MB. Not all OpenWhisk deployments support this out-of-the-box.
> The deployment section below shows an example of changing the default function memory limit from 512 MB to a higher value.

### Deployment

In `tools/openwhisk_preparation.py`, we include scripts that help install
[kind (Kubernetes in Docker)](https://kind.sigs.k8s.io/) and deploy
OpenWhisk on a `kind` cluster. Alternatively, you can deploy to an existing
cluster by [using offical deployment instructions](https://github.com/apache/openwhisk-deploy-kube/blob/master/docs/k8s-kind.md):

```shell
./deploy/kind/start-kind.sh
helm install owdev ./helm/openwhisk -n openwhisk --create-namespace -f deploy/kind/mycluster.yaml
kubectl get pods -n openwhisk --watch
```

To change the maximum memory allocation per function, edit the `max` value under `memory` in file `helm/openwhisk/values.yaml`.
To run all benchmarks, we recommend of at least "2048m".

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

OpenWhisk has a `shutdownStorage` switch that controls the behavior of SeBS.
When set to true, SeBS will remove the Minio instance after finishing all work.

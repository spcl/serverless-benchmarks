# Platform Configuration

SeBS supports four commercial serverless platforms: AWS Lambda, Azure Functions, Google Cloud Functions, and Cloudflare Workers.
Furthermore, we support the open source FaaS system OpenWhisk.

The file `configs/example.json` contains all parameters that users can change
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

### Multi-platform Docker Images

Build images, which encapsulate package building, are available as both x64 and arm64 for Python and Node.js on AWS Lambda.
To rebuild multi-plaform images, an additional flag is needed to enable the internal `docker buildx` command:

```bash
sebs docker build --image-type build --language python --deployment aws --architecture x64 --language-version 3.11 --multi-platform
```

When rebuilding build images (not necessary for regular users, only for developers), make sure that your Docker installation supports multi-platform images, e.g., [you use `containerd` image store](https://docs.docker.com/engine/storage/containerd/) - old Docker installations might not change the storage type after an upgrade to Docker 29.0, where `containerd` is the default.

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
To use a user-defined lambda role, set the name in config JSON - see an example in `configs/example.json`.

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

### Lambda Function URLs vs API Gateway

SeBS supports two methods for HTTP-based function invocation on AWS Lambda:

1. **Lambda Function URLs** (default) - Direct Lambda invocations.
2. **API Gateway HTTP API** (optional) - Traditional approach using AWS API Gateway.

SeBS used API Gateway to trigger Lambda functions. However, API Gateway has a hard timeout limit of 29 seconds, which can be restrictive for long-running benchmarks. To overcome this limitation and simplify the architecture, we added support for Lambda Function URLs, which allow direct invocation of Lambda functions without the need for API Gateway. Since we do not rely on more complex API management features, function URLs are now the default version.

However, API gateway can still be used to benchmarking. The switch between both options is configured in the deployment settings:

```json
"deployment": {
  "name": "aws",
  "aws": {
    "region": "us-east-1",
    "resources": {
      "use-function-url": true,
      "function-url-auth-type": "NONE"
    }
  }
}
```

> [!WARNING]
> SeBS implements the "NONE" authentication mode for function URLs, making Lambda functions publicly accessible without any authentication.

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

Login successful with user {'name': 'ZZZZZZ', 'type': 'user'}
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
> Sometimes there's a delay within Azure platform that causes properties like subscription assignment to not be propagated immediately across systems. If you keep seeing errors such "No subscription found", then wait for a few minutes before trying again.

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
    "project_name": "your-gcp-project-id",
    "credentials": "/path/to/project-credentials.json"
  }
}
```

### Deployment Modes

SeBS models three GCP deployment targets:

1. `function-gen1`: the first Google Cloud Functions Gen1 path.
2. `function-gen2`: Google Cloud Functions Gen2 package deployment.
3. `container`: direct container deployment to Cloud Run.
These deployment types intentionally share a single GCP backend in SeBS, but they are not identical in packaging, naming, scaling, or performance behavior.

On GCP, there are two different concurrency layers that should not be confused:
* platform concurrency: how many requests GCP may send to one instance (`gcp-concurrency`)
* runtime concurrency: how many requests the language server is prepared to process internally (`worker-concurrency`, `worker-threads`)
This design is intentional. A single Cloud Run concurrency number is not enough to reason about performance if the application server is underprovisioned or overprovisioned relative to the platform.

### Function Gen1

Gen1 is the currently implemented Google-managed function deployment path in SeBS. The packaging flow is ZIP-based:
* benchmark sources are moved into a `function/` subdirectory,
* the language wrapper file is renamed to the GCP-required entrypoint name (`main.py` for Python, `index.js` for Node.js),
* the whole directory is archived and uploaded to Cloud Storage,
* Cloud Functions Gen1 is then updated from the uploaded archive.

Gen1 configuration currently exposes instance-scaling controls:

```json
"deployment": {
  "name": "gcp",
  "gcp": {
    "region": "europe-west1",
    "project_name": "your-gcp-project-id",
    "credentials": "/path/to/project-credentials.json",
    "configuration": {
      "function-gen1": {
        "min-instances": 0,
        "max-instances": 20
      }
    }
  }
}
```

Use Gen1 when you want the most established GCP path in SeBS and do not need container-level runtime tuning.

### Function Gen2

Gen2 reuses the same local ZIP packaging flow as Gen1, but deploys through the Cloud Functions v2 API. It is selected directly through the experiment-level `system_variant`:

```json
"deployment": {
  "name": "gcp",
  "gcp": {
    "region": "europe-west1",
    "project_name": "your-gcp-project-id",
    "credentials": "/path/to/project-credentials.json",
    "configuration": {
      "function-gen2": {
        "vcpus": 1,
        "gcp-concurrency": 80,
        "worker-concurrency": 1,
        "worker-threads": 8,
        "min-instances": 0,
        "max-instances": 20,
        "cpu-boost": false,
        "cpu-throttle": true
      }
    }
  }
}
```

Set `experiments.system_variant` to one of `function-gen1`, `function-gen2`, or `container`. From the CLI and regression workflows, the same selection is exposed through the generic `--system-variant` option.

Gen1 and Gen2 package deployments use separate SeBS cache identities and separate cloud function names with short `-gen1` and `-gen2` suffixes. This avoids control-plane races when switching between package modes. In practice, regression and benchmark runs should still select one GCP package mode at a time for a given run.

### Cloud Run Container Deployments

Container deployments are the currently implemented Cloud Run-based path in SeBS. They are selected with container deployment and use a provider-specific function image built from `Dockerfile.function`.
At the deployment level, SeBS configures Cloud Run service properties:

```json
"deployment": {
  "name": "gcp",
  "gcp": {
    "region": "europe-west1",
    "project_name": "your-gcp-project-id",
    "credentials": "/path/to/project-credentials.json",
    "configuration": {
      "container": {
        "environment": "gen2",
        "vcpus": 1,
        "gcp-concurrency": 80,
        "worker-concurrency": 80,
        "worker-threads": 8,
        "min-instances": 0,
        "max-instances": 20,
        "cpu-boost": false,
        "cpu-throttle": true
      }
    }
  }
}
```

For Python, SeBS uses [`functions-framework`](https://github.com/GoogleCloudPlatform/functions-framework-python) behind `gunicorn` rather than the framework's default development server, as [recommended by Cloud Run performance guidance](https://docs.cloud.google.com/run/docs/tips/python).
For Node.js, SeBS uses [`@google-cloud/functions-framework`](https://github.com/GoogleCloudPlatform/functions-framework-nodejs) started directly with `node` rather than via `npm start`, [as recommended by Cloud Run performance guidance](https://docs.cloud.google.com/run/docs/tips/nodejs).
For Java, we use [`java-function-invoker`](https://mvnrepository.com/artifact/com.google.cloud.functions.invoker/java-function-invoker), and we disable tiered compilation to speed up startup time, [as recommended by Cloud Run performance guidance](https://docs.cloud.google.com/run/docs/tips/java).

Cloud Run containers can [execute in two environments](https://docs.cloud.google.com/run/docs/configuring/execution-environment): gVisor-based gen1, and VM-based gen2.

### Current Limitations

The current GCP backend has the following practical limits:
* Gen1 is the primary managed-functions deployment path today.
* Gen2 supports the ZIP package deployment path and HTTP triggers.
* Library-trigger direct invocation remains Gen1-only.
* Cloud Run containers are implemented today and provide the most tuning control.
* GCP deployments currently reject `arm64`, as arm64 instances are not available for GCR.
* C++ packaging is not supported on GCP (but possible to be implemented on containers).

## Cloudflare Workers

> [!NOTE]
> **Terminology mapping**: SeBS uses the term *function* throughout its CLI and configuration. On Cloudflare, the equivalent unit of deployment is a **Worker**. Wherever SeBS refers to a function (e.g. `--function-name`, `create_function`, `CloudflareWorker`), it refers to a Cloudflare Worker script deployed to `{name}.{account}.workers.dev`.

Cloudflare offers a free tier for Workers with generous limits for development and testing. To use Cloudflare Workers with SeBS, you need to create a Cloudflare account and obtain API credentials.

### Credentials

SeBS supports both authentication methods Cloudflare offers. Both are
functionally equivalent for SeBS: every API call, R2 upload, KV
operation, and `wrangler` invocation works with either. Pick based on
your Cloudflare account, not on SeBS features:

- **API Token (recommended)**: A scoped credential you mint in the
  Cloudflare dashboard. It can be limited to the permissions SeBS needs
  and revoked independently, so this is the safest default for most
  users.
- **Email + Global API Key (legacy)**: Your account email plus the
  Global API Key from the Cloudflare dashboard. SeBS still supports this
  path for older setups and accounts that cannot use scoped tokens, but
  it grants broad account access and should be handled more carefully.

Regardless of which method you choose, you also need your account ID
from the Cloudflare dashboard.

You can pass credentials using environment variables:

```bash
# Option 1: API Token (recommended)
export CLOUDFLARE_API_TOKEN="your-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"

# Option 2: Email + Global API Key (legacy)
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

SeBS uses a containerized CLI approach for Cloudflare deployments, eliminating the need to install Node.js, npm, wrangler, pywrangler, or uv on your host system. The CLI container (`spcleth/serverless-benchmarks:manage.cloudflare`) is pulled from Docker Hub on first use and contains all necessary tools. This ensures consistent behavior across platforms and simplifies setup — only Docker is required.

To build and push an updated `manage.cloudflare` image (developers only):

```bash
sebs docker build --deployment cloudflare --image-type manage
sebs docker push --deployment cloudflare --image-type manage
```

#### Shared singleton and lifecycle

`CloudflareCLI` is a process-wide singleton: both the script-based (`workers.py`) and container-based (`containers.py`) deployment handlers share a single `manage.cloudflare` Docker container. The first call to `CloudflareCLI.get_instance()` starts the container and registers a shutdown hook via `atexit`; subsequent calls from any handler or thread return the already-running instance.

This has two consequences:

- **Thread safety during creation** — `get_instance()` uses a double-checked lock so that when multiple benchmarks run in parallel (e.g. during `sebs regression`), only one thread starts the container while the others wait.
- **Lifecycle** — individual deployment handlers (and `Cloudflare.shutdown()`) drop their local reference to the instance but do not stop the container. The container is stopped exactly once at process exit by the `atexit` hook, regardless of whether SeBS is invoked directly (`sebs benchmark invoke`) or through the regression suite.

### Deployment Architecture

SeBS supports two deployment paths for Cloudflare: **script-based Workers** (native Workers runtime) and **container-based Workers** (Cloudflare's managed container runtime, fronted by a Durable-Object-backed Worker). Both paths share the same credentials, R2/KV resources, and HTTP trigger; they differ only in how code is packaged and which Cloudflare runtime executes it. The deployment type is controlled by the benchmark's `container_deployment` flag.

#### Python modules (`sebs/cloudflare/`)

| File | Responsibility |
|------|----------------|
| `cloudflare.py` | `Cloudflare(System)` facade. Verifies credentials, enforces `SUPPORTED_BENCHMARKS`, resolves the `workers.dev` URL, and dispatches `package_code`/`create_function`/`update_function` to the correct handler via `_get_deployment_handler(container_deployment)`. |
| `workers.py` | `CloudflareWorkersDeployment` — native script packaging. Node.js is bundled with esbuild via `nodejs/Dockerfile.build`; Python generates a `pyproject.toml` and is validated via `python/Dockerfile.build` (Pyodide resolution happens server-side at deploy time). |
| `containers.py` | `CloudflareContainersDeployment` — container packaging. Copies the per-language `Dockerfile.function` into the code directory, injects the `worker.js` orchestrator (Node-only, required by `@cloudflare/containers`), merges `package.json`, runs `npm install`, and builds a local image as a cache anchor. |
| `cli.py` | `CloudflareCLI` — runs the `manage.cloudflare` Docker container with the Docker socket mounted and exposes `wrangler_deploy`, `pywrangler_deploy`, `docker_build`, `upload_package`. Used by both deployment handlers; `cloudflare.py` never calls `wrangler` directly. |
| `config.py` | `CloudflareCredentials` / `CloudflareConfig` — API token, account ID, R2 keys. |
| `resources.py` | `CloudflareSystemResources` — factories for R2 and KV/Durable Objects. |
| `function.py` | `CloudflareWorker(Function)` — cached function metadata. |
| `triggers.py` | `HTTPTrigger` — invokes the deployed Worker at `https://{name}.{account}.workers.dev`. |
| `r2.py`, `kvstore.py` | Object and NoSQL storage clients. |

Wrangler templates live alongside the deployment code at `sebs/cloudflare/templates/wrangler-worker.toml` and `sebs/cloudflare/templates/wrangler-container.toml` so they ship with the pip-packaged `sebs`.

#### Dockerfiles (`dockerfiles/cloudflare/`)

| File | Purpose |
|------|---------|
| `Dockerfile.manage` | Builds the `manage.cloudflare` CLI image (Node + global `wrangler` + `pywrangler` via `uv` + Docker CLI). Driven by `cli.py`. |
| `nodejs/Dockerfile.build` | Build image for **script-based** Node.js workers. Pulled once per session; benchmark source is bind-mounted to `/mnt/function` at build time and `cloudflare_nodejs_installer.sh` runs `npm install`, `esbuild`, and the benchmark's `build.js`/`postprocess.js` inside it. |
| `python/Dockerfile.build` | Build image for **script-based** Python workers. Pulled once per session; benchmark source is bind-mounted to `/mnt/function` at build time and `cloudflare_python_installer.sh` validates that `pywrangler` accepts the generated `pyproject.toml`. |
| `nodejs/Dockerfile.function` | Runtime image for **container-based** Node.js functions. Parameterized via `ARG BASE_IMAGE` from `config/systems.json`. Copied into the package by `containers.py` and rebuilt by `wrangler deploy`. |
| `python/Dockerfile.function` | Runtime image for **container-based** Python functions. Same parameterization. |

#### Script-based flow (`container_deployment=false`)

1. `benchmark.build()` → `CloudflareWorkersDeployment.package_code` copies source files into the package directory.
2. `Benchmark.install_dependencies()` pulls the matching `spcleth/serverless-benchmarks:build.cloudflare.<lang>.<ver>` build image (see [Build Images](#build-images) below), bind-mounts the package directory to `/mnt/function`, and runs `/sebs/installer.sh` (`cloudflare_nodejs_installer.sh` or `cloudflare_python_installer.sh`) inside the container.
3. `Cloudflare.create_function` → `_create_or_update_worker` renders `sebs/cloudflare/templates/wrangler-worker.toml` into the package.
4. `CloudflareCLI.wrangler_deploy` (Node) or `pywrangler_deploy` (Python) deploys via the `manage.cloudflare` container.
5. `HTTPTrigger` is attached using the `workers.dev` URL.

#### Container-based flow (`container_deployment=true`)

1. **Local image build** — `benchmark.build()` calls `container_client.build_base_image()` on the `_CloudflareContainerAdapter` in `cloudflare.py`, which delegates to `CloudflareContainersDeployment.package_code`. It copies `{language}/Dockerfile.function` as `Dockerfile`, adds `worker.js`, merges `package.json`, and builds a local Docker image tagged `<name>:<timestamp>` (e.g. `my-benchmark-python-312:20260426-130338`). The correct `BASE_IMAGE` is passed via Docker build args (resolved from `systems.json`). A timestamp tag is used instead of `:latest` because Cloudflare's registry explicitly rejects `:latest` tags.

2. **Registry push** — `Cloudflare.create_function` → `_create_or_update_worker` calls `CloudflareCLI.containers_push(<name>:<timestamp>)`, which runs `wrangler containers push` inside the `manage.cloudflare` container. Wrangler uploads the locally-built image to Cloudflare's managed registry and returns the full registry URI: `registry.cloudflare.com/<account_id>/<name>:<timestamp>`.

3. **`wrangler.toml` generation** — `_generate_wrangler_toml` renders `sebs/cloudflare/templates/wrangler-container.toml`. The template defaults to `image = "./Dockerfile"` (a local build path). When a registry URI is available, `containers.py` replaces this field with the registry URI (`config['containers'][0]['image'] = container_uri`), so wrangler points directly at the pre-pushed image and skips rebuilding the Dockerfile entirely.

4. **Deploy** — `CloudflareCLI.wrangler_deploy` runs `npm install && wrangler deploy` inside the `manage.cloudflare` container. `npm install` materializes `node_modules/@cloudflare/containers` (listed in `package.json`) so that wrangler's bundler can resolve the `worker.js` import. Wrangler then deploys the Worker script and creates the Durable-Object-backed container worker backed by the registry image.

5. `wait_for_durable_object_ready` polls `/health` until the container reports healthy, then SeBS pings `/health` for ~60 s to keep the Durable Object alive during the container provisioning window before the first measured invocation.

6. `HTTPTrigger` is attached using the `workers.dev` URL.

### Build Images

Script-based Worker builds use pre-built build images that are pulled once and reused across all benchmarks via bind-mounts — this is the same pattern SeBS uses for other platforms (see [build.md](build.md)). The images are tagged `spcleth/serverless-benchmarks:build.cloudflare.<lang>.<ver>` (e.g. `build.cloudflare.nodejs.18`, `build.cloudflare.python.3.12`) and are available on Docker Hub.

To build and push updated images yourself (e.g. after modifying a `Dockerfile.build` or an installer script):

```bash
# Build all Cloudflare toolchain images locally
sebs docker build --deployment cloudflare

# Push them to Docker Hub (requires push access to the repository)
sebs docker push --deployment cloudflare
```

To use a different Docker Hub repository, change `['general']['docker_repository']` in `configs/systems.json`.

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
- **Wall-Clock Timing**: Cloudflare Workers freezes `Date.now()` and `performance.now()` between I/O operations as a timing side-channel mitigation, so the clock does not advance inside pure-compute sections. To record a meaningful wall-clock `compute_time`, the handler issues a throwaway self-fetch (a `HEAD /favicon` request) before sampling the end time. This I/O call unfreezes the timer. See the [Cloudflare security model docs](https://developers.cloudflare.com/workers/reference/security-model/#step-1-disallow-timers-and-multi-threading) for details.
- **Metrics Collection**: Uses response-based per-invocation metrics. During each function invocation, the worker handler measures performance metrics (CPU time, wall time, memory usage) and embeds them directly in the JSON response. SeBS extracts these metrics immediately from each response. When `download_metrics()` is called for postprocessing, it only aggregates the metrics that were already collected during invocations—no additional data is fetched from external services. This approach provides immediate per-invocation granularity without delays. Note that while Cloudflare does expose an Analytics Engine, it only provides aggregated metrics without individual request-level data, making it unsuitable for detailed benchmarking purposes.

### Storage Configuration

Cloudflare Workers integrate with Cloudflare R2 for object storage and Durable Objects for NoSQL storage. For detailed storage configuration, see the [storage documentation](storage.md#cloudflare-storage).

## OpenWhisk

SeBS expects users to deploy and configure an OpenWhisk instance.
Below, you will find example of instruction for deploying OpenWhisk instance.
The configuration parameters of OpenWhisk for SeBS can be found
in `configs/example.json` under the key `['deployment']['openwhisk']`.
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

> [!NOTE]
> On Python and Node.js, we create a full Docker image and upload the main handler
file only to OpenWhisk, as this is required for actions.
This is not possible on Java, as we need to compile the code into JAR.
To avoid extract build image, we build the function image, extract the function JAR,
and upload it with the action. In future, if we want to create heavy JARs with complex
dependencies, we might need to switch to full image deployment on Java as well.


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
`['general']['docker_repository']` in `configs/systems.json`.

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

> [!WARNING]
> This feature is experimental and has not been tested extensively. At the moment, it cannot be used on a `kind` cluster due to issues with Docker authorization on invoker nodes. [See the OpenWhisk issue for details](https://github.com/apache/openwhisk-deploy-kube/issues/721).

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

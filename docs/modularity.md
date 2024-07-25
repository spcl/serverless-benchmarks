
## Modularity

SeBS benchmarks have been designed to operate independently of the underlying serverless platform.
We provide a single benchmark implementation with additional scripts to install dependencies and generate inputs.
In addition, we support the automatic deployment of benchmarks to three commercial
platforms, one open-source platform (Open Whisk), and local Docker serving. The automatic
deployment implements creating and updating functions on the serverless platform, exposing
invocation API, and deploying storage.

In this document, we explain how to extend SeBS with new benchmarks, languages, experiments,
and how to support new commercial and open-source FaaS platforms.

* [How to add new benchmarks?](#new-benchmarks)
* [How to run benchmarks on an unsupported serverless platform?](#running-on-unsupported-platform)
* [How to add a new programming language to benchmarks?](#new-languages)
* [How to add support for a new serverless platform?](#new-serverless-platform)
* [How to add a new experiment?](#new-experiments)


## New Benchmarks

Benchmarks follow the naming structure `x.y.z` where x is the benchmark group, y is the benchmark
ID and z is benchmark version. For examples of implementations, look at `210.thumbnailer`
or `311.compression`. Benchmark requires the following files:

#### Configuration

**config.json** defines the default timeout, memory size, and languages supported for this benchmark.
The usual convention is that `memory` defines the lowest memory amount for which this benchmark can be executed
on all platforms.

```json
{
  "timeout": 60,
  "memory": 256,
  "languages": ["python", "nodejs"]
}
```

#### Input Data

**input.py** implements input generation for the benchmark. There is a single Python file with such an implementation
for all language implementations of the benchmark - input generation is always the same.

```python
'''
  :return: number of input and output buckets necessary 
'''
def buckets_count():
    return (1, 1)

'''
    Generate test, small and large workload for thumbnailer.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
    :return: input config for benchmark
'''
def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):

```

Input files for benchmark, e.g., pretrained model and test images for deep learning inference, should be added to the [benchmarks-data](https://github.com/spcl/serverless-benchmarks-data) repository. SeBS will upload all inputs to the cloud storage, as implemented in the `generate_input` function in `input.py` file. Output buckets are cleaned after experiments. Furthermore, this function should return input configuration as a dictionary that will be passed to the function at invocation.

#### Code

Place source code and internal resources in the language directory, e.g., `python` or `nodejs`. The entrypoint should be located in a file named `function.<language-extension>`, e.g., `function.py` or `function.js`, and take just one argument:

```python
def handler(event):
```

Dependencies are installed automatically, as configured in `requirements.txt` or `package.json`. By default, only the source code is deployed. If you need additional resources in the new benchmark, e.g., HTML template, use the script `init.sh` (see an example in `110.dynamic-html` or in `220.video-processing`).

**Important** By default, SeBS deploys code packages using code packages.
Starting from the OpenWhisk addition in release 1.1, we are adding function
deployment as Docker images. Docker images with existing benchmarks
are available on [Docker Hub](https://hub.docker.com/repository/docker/spcleth/serverless-benchmarks).
When adding a new benchmark, it is possible to use a local Docker registry
to push images with the new functions - see [OpenWhisk documentation for details](platforms.md).

## Running on Unsupported Platform

Do you want to deploy our benchmarks to a platform we do not currently support? No problem!
You can easily create functions from our benchmark code, as all benchmarks are platform-independent.
The provider-specific invocation and storage APIs are implemented in lightweight wrappers in [`benchmarks/wrappers/{platform}`](/benchmarks/wrappers).
To add a new `handler` wrapper, you only need to process the cloud-specific input, import the function, and call it with the actual function input.
To add a new `storage` wrapper, you must implement basic upload, download, and list functionalities of the persistent object storage of the new cloud platform.

Depending on the language, such as Python or Node.js, it is sufficient to install dependencies using
provided configuration file, implement the wrapper for the new platform, pack the code according
to the platform's requirements, and a new function can be created.
For each benchmark, the `input.py` file provides a generation of inputs and upload of benchmark input data to cloud storage.

## New Languages

At the moment, SeBS implements benchmarks in Python and Node.js. However, it is very easy to add new languages,
and it requires only minor modifications.

#### Language Name

First, pick a language name and use it consistently in all places.
For example, we use `nodejs` for benchmarks in Node.js; it is important we never refer to such
benchmarks with another name, e.g., `node.js` or `node`.

#### Add Docker Builder Image

For each new language, we need to add a Docker image used for building and installing function dependencies.
The container will be run during the function build, and SeBS will mount the function code and configuration inside the container.
The main part of the container image is an installer script that implements language-specific installation of function dependencies.
To add a new language, we need:
1. Docker base image.
2. New Dockerfile.build file.
3. New language-specific installer called `{lang}_installer.sh`.

First, we need a base image.
A good choice is to use an official image for the language released by the cloud provider when available.
Otherwise, use an image that closely resembles the runtime environment of a function.
For already supported serverless platforms, you can find examples in [`config/systems.json`](/config/systems.json).

Once we have a base image and add it to the configuration, we need to add a new `Dockerfile.build` file to `dockerfiles/{platform}/{language}`.
At the image build time, this file will be provided with two arguments: `BASE_IMAGE` and `VERSION`, which specifies the language version used.
See the example for Python:

```
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG VERSION
ENV PYTHON_VERSION=${VERSION}
```

Then, add the generic code, which allows for non-root containers. Here is an example for CentOS:

```
RUN yum install -y shadow-utils zip
ENV GOSU_VERSION 1.14
# https://github.com/tianon/gosu/releases/tag/1.14
# key https://keys.openpgp.org/search?q=tianon%40debian.org
RUN curl -o /usr/local/bin/gosu -SL "https://github.com/tianon/gosu/releases/download/${GOSU_VERSION}/gosu-amd64" \
    && chmod +x /usr/local/bin/gosu
RUN mkdir -p /sebs/
```

Finally, we add the language-specific installer and the entrypoint script for the builder image.

```
COPY dockerfiles/python_installer.sh /sebs/installer.sh
COPY dockerfiles/entrypoint.sh /sebs/entrypoint.sh
RUN chmod +x /sebs/entrypoint.sh
```

The `{lang}_installer.sh` is cloud-independent and implements installing function dependencies.
It should take no arguments and change the directory to `/mnt/function`, where the benchmark code is located.
Actual installation depends on the programming language.
For example, Python uses `pip` to install dependencies specified in `requirements.txt`, and 
Node.js uses `npm` to install packages described in `package.json`.

Finally, the image contains the definition of the entrypoint.

```
# useradd and groupmod is installed in /usr/sbin which is not in PATH
ENV PATH=/usr/sbin:$PATH
ENV SCRIPT_FILE=/mnt/function/package.sh
CMD /bin/bash /sebs/installer.sh
ENTRYPOINT ["/sebs/entrypoint.sh"]
```

#### Extend Configuration

Then, we need to add the new language in [`config/systems.json`](/config/systems.json).

```json
"languages": {
  "python": {
    "base_images": {
      "<language_version>": "<image>"
    },
    "versions": [
      "<language_version>"
    ],
    "images": [
      "build"
    ],
    "deployment": {
      "files": [
        <benchmark-language-wrappers>
      ],
      "packages": []
    }
  }
}
```

Once done, we can build the image with `tools/build_docker_images.py`.

#### Benchmark Wrappers

For each language and cloud platform, we need to implement benchmark wrappers.
The two most common are `handler` which interface cloud-specific function API,
and `storage` which hides the cloud API of persistent storage.

For example, examine the existing implementations in [`benchmarks/wrappers/`](/benchmarks/wrappers/).

#### Adapt Platform Mode

The final step is adjusting the SeBS code whenever we make a language-specific decision.
We need to tell the `package_code` function which files need to be uploaded.
This includes the `handler` wrapper and installed dependencies.

Example for AWS:

```python
CONFIG_FILES = {
    "python": ["handler.py", "requirements.txt", ".python_packages"],
    "nodejs": ["handler.js", "package.json", "node_modules"],
}
```

Example for Azure:

```python
EXEC_FILES = {"python": "handler.py", "nodejs": "handler.js"}
CONFIG_FILES = {
    "python": ["requirements.txt", ".python_packages"],
    "nodejs": ["package.json", "node_modules"],
}
```

And now we can start adding benchmarks in new languages!

## New Serverless Platform

The full power and ease of use of SeBS are enabled by launching experiments automatically on a
specified platform. If your serverless platform is not currently supported in SeBS, it
can easily be added by implementing a few functions in Python. The main goal of the implementation is to encapsulate
REST APIs and SDKs of the different platforms behind a common interface.

The main interface of the serverless platform is provided in the [`sebs.faas.system.System`](/sebs/faas/system.py).
Each platform implements a class that inherits from it and implements the necessary components.

#### Configuration

First, add your platform to the configuration in [`systems.json`](/config/systems.json).
Check other platforms to see how configuration is defined, for example, for AWS:

```json
"aws": {
    "languages": {
      "python": {
        "base_images": {
          "3.9": "amazon/aws-lambda-python:3.9",
          "3.8": "amazon/aws-lambda-python:3.8",
          "3.7": "amazon/aws-lambda-python:3.7"
        },
        "versions": [
          "3.7",
          "3.8",
          "3.9"
        ],
        "images": [
          "build"
        ],
        "deployment": {
          "files": [
            "handler.py",
            "storage.py"
          ],
          "packages": []
        }
      }
    }
}
```
 
You need to provide the following settings:

* Which programming languages are supported? Which versions of the language?
* Which Docker images should be used as the sandbox for building code deployment? Usually, we use the default ones
released by the cloud provider. No need for a specific image? The default Ubuntu/Debian one might be a good choice.
* Which files should be provided with the deployment? The default choice is to provide the `handler`
and `storage` wrappers of benchmarks.
* Does the benchmark require installing additional packages used by all functions? Examples are cloud storage SDKs in Azure Functions and Google Cloud Functions.

Now, extend the enum types in [`sebs.types`](/sebs/types.py) to add the new platform.

#### Preparing benchmark upload

The first step is to tell SeBS how the code package should be built for the new platform. SeBS
will install dependencies and copy code into a single location, but it needs
to be told how files should be arranged as this is platform-dependent. Similarly, platforms
might require zipping the file (AWS) or adding JSON configuration to each function (Azure).
Implement this step in the following function:

```python
    def package_code(
        self,
        directory: str,
        language_name: str,
        language_version: str,
        benchmark: str,
        is_cached: bool,
    ) -> Tuple[str, int]
```

The function should return the path to the final code package and its size.

Need to build a Docker image? See the [OpenWhisk implementation](/sebs/openwhisk/openwhisk.py) for
details.

#### Creating and launching function

SeBS caches cloud functions to avoid recreating functions on each restart.
Depending on the cache status, SeBS might create a new function; it can retrieve a function from the local cache and use it;
or retrieve a function from the local cache and update the cloud's version.
The latter happens when the code has been modified locally, and the code package has been rebuilt,
or the user has requested updating the cloud's version.

Each platform needs to implement these three major functionalities.

```python
    def create_function(self, code_package: Benchmark, func_name: str) -> Function:
```

This function creates a new function and uploads the provided code.
If a function with such a new name already exists on the platform, it should be updated with
the provided code.

The function should have the default trigger, either an SDK or an HTTP trigger -
see existing implementations for details.

```python
    def cached_function(self, function: Function):
```

This function has been retrieved from the cache and requires refreshing function triggers.
In practice, this is often limited to updating logging handlers - see existing implementations for details.

```python
    def update_function(self, function: Function, code_package: Benchmark):
```

This function updates the function's code and configuration in the platform.

```python
    def create_trigger(self, function: Function, trigger_type: Trigger.TriggerType) -> Trigger:
```

Each platform defines which function triggers are supported, and this function adds a trigger of a given type.
Currently, we support library SDK and generic HTTP triggers.

Finally, there is an additional function that implements updating the function configuration but not its code.
For example, on AWS and GCP it implements updating the memory configuration of a function.

```python
    def update_function_configuration(self, cached_function: Function, benchmark: Benchmark):
        pass
```

#### Storage

Most of our benchmarks use cloud object storage to store inputs and output.
We use the available object storage on cloud systems, such as AWS S3 and Azure Blob Storage.
We implement support from them by adding a new class that inherits from the [`sebs.faas.storage.PersistentStorage`](/sebs/faas/storage.py)
The implementation needs to expose the storage instance via an API method:

```python
    def get_storage(self, replace_existing: bool) -> PersistentStorage:
```

Your platform does not come with object storage? No worries, you can then deploy the Minio storage!
SeBS includes automatic deployment of an instance of this storage, and our benchmarks can use it -
see OpenWhisk documentation, as it uses Minio for storing benchmark inputs and outputs.

#### Other

A few additional methods need to be defined:

```python
    def default_function_name(self, code_package: Benchmark) -> str:
```

Generates a default name of a function - it should include benchmark name, language name,
and language version.

```python
    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
```

Force the platform to kill all warm containers so the next invocation will be cold.
Most platforms do not provide this feature; we implement this by updating the function's configuration,
e.g., by changing the environment variables.

```python
    def download_metrics(
        self,
        function_name: str,
        start_time: int,
        end_time: int,
        requests: Dict[str, ExecutionResult],
        metrics: dict,
    ):
```

Downloads from the cloud metrics on the provided function invocations - time used, time billed,
memory used. Implement an empty function if your system does not store any metrics.

## New Experiments

Implement the interface in `sebs/experiment/experiment.py` and
add the new experiment type to the CLI initialization in
[`sebs/sebs.py`](https://github.com/spcl/serverless-benchmarks/blob/master/sebs/sebs.py#L108).

Then, you will be able to invoke the experiment from CLI, and SeBS will handle the initialization
of cloud resources.

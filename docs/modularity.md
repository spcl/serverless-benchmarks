
## Modularity

SeBS benchmarks have been designed to operate independently of the underlying serverless platform.
We provide a single benchmark implementation with additional scripts to install dependencies and generate inputs.
In addition, we support the automatic deployment of benchmarks to three commercial
platforms, one open-source platform (Open Whisk), and local Docker serving. The automatic
deployment implements creating and updating functions on the serverless platform, exposing
invocation API, and deploying storage.

In this document, we explain how to extend SeBS with new benchmarks and experiments,
and how to support new commercial and open-source FaaS platforms.

### How to run benchmarks on a new serverless platform?

Do you want to deploy our benchmarks to a platform we do not currently support? No problem!
You can easily create functions from our benchmark code, as all benchmarks are platform-independent.
The provider-specific invocation and storage APIs are implemented in lightweight wrappers in [`benchmarks/wrappers/{platform}`](/benchmarks/wrappers).

Depending on the language, such as Python or Node.js, it is sufficient to install dependencies using
provided configuration file, provide the wrapper for the new platform, pack the code according
to the platform's requirements, and the new function can be created.
For each benchmark, the `input.py` file provides generation of inputs and implements uploading benchmarks input data to cloud storage.

### How to add support for a new serverless platform?

The full power and ease-of-use of SeBS is enabled by launching experiments automatically on a
specified platform. If your serverless platform is not currently supported in SeBS, it
can easily be added by implementing a few functions in Python. The main goal of the implementation is to encapsulate
REST APIs and SDKs of the different platforms behind a common interface.

The main interface of the serverless platform is provided in the [`sebs.faas.system.System`](/sebs/faas/system.py).
Each platform implements a class that inherits from it and implements the necessary components.

#### Configuration

First, add your platform to the configuration in [`systems.json`](/config/systems.json).
Check other platforms to see how configuration is defined. You need to provide the following
settings:

* Which programming languages are supported? Which versions of the language?
* Which Docker images should be used as the sandbox for building code deployment? No need for a specific
image? The default Ubuntu/Debian one might be a good choice.
* Which files should be provided with the deployment? The default choice is to provide the `handler`
and `storage` wrappers of benchmarks.
* Does the benchmark require installing additional packages that are used by all functions? Examples
are cloud storage SDKs in Azure Functions and Google Cloud Functions.

Now, extend the enum types in [`sebs.types`](/sebs/types.py) to add the new platform.

#### Preparing benchmark upload

The first step is to tell SeBS how the code package should be built for the new platform. SeBS
will take care of installing dependencies and copying code into a single location, but it needs
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

The function should return the path to the final code package and package size.

Need to build a Docker image? See the [OpenWhisk implementation](/sebs/openwhisk/openwhisk.py) for
details.

#### Creating and launching function

SeBS caches cloud functions to avoid recreating functions on each restart.
Depending on the cache status, SeBS might create a new function, it can retrieve a function from the local cache and use it,
or it can retrieve a function from the local cache and update the cloud's version.
The latter happens when the code has been modified locally and the code package has been rebuilt,
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

#### Storage

Most of our benchmarks use cloud object storage to store inputs and output.
We use the available object storage on cloud systems, such as AWS S3 and Azure Blob Storage.
The implementation needs to expose the storage via an API method:

```python
    def get_storage(self, replace_existing: bool) -> PersistentStorage:
```

Your platform does not come with object storage? No worries, you can then deploy the Minio storage!
SeBS includes automatic deployment of an instance of this storage and our benchmarks can use it -
see OpenWhisk documentation as it uses Minio for storing benchmark inputs and outputs.

#### Other

Few additional methods need to be defined:

```python
    def default_function_name(self, code_package: Benchmark) -> str:
```

Generates a default name of a function - it should include benchmark name, language name,
and language version.

```python
    def enforce_cold_start(self, functions: List[Function], code_package: Benchmark):
```

Force the platform to kill all warm containers such that the next invocation will be cold.
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


### How to add new benchmarks?

Benchmarks follow the naming structure `x.y.z` where x is benchmark group, y is benchmark
ID and z is benchmark version. For examples of implementations, look at `210.thumbnailer`
or `311.compression`. Benchmark requires the following files:

**config.json**
```json
{
  "timeout": 60,
  "memory": 256,
  "languages": ["python", "nodejs"]
}
```

**input.py**
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

Input files for benchmark, e.g. pretrained model and test images for deep learning inference, will be uploaded to input benchmark according `generate_input`. Output buckets are cleaned after experiments. The function should return input configuration in form of a dictionary that will be passed to the function at invocation.

Then place source code and resources in `python` or `nodejs` directories. The entrypoint should be located in file named `function` and take just one argument:

```python
def handler(event):
```

Configure dependencies in `requirements.txt` and `package.json`. By default, only  source code is deployed. If you need to use additional resources, e.g., HTML template, use script `init.sh` (see an example in `110.dynamic-html`).

**Important** By default, SeBS deploys code packages using code packages.
Starting from OpenWhisk addition in release 1.1, we are adding function
deployment as Docker images. Docker images with existing benchmarks
are available on [Docker Hub](https://hub.docker.com/repository/docker/spcleth/serverless-benchmarks).
When adding a new benchmark, it is possible to use a local Docker registry
to push images with the new functions - see [OpenWhisk documentation for details](platforms.md).

### How to add a new experiment?

Implement the interface in `sebs/experiment/experiment.py` and
add the new experiment type to the CLI initialization in
[`sebs/sebs.py`](https://github.com/spcl/serverless-benchmarks/blob/master/sebs/sebs.py#L108).

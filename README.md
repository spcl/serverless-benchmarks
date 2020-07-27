
# SeBS: Serverless Benchmark Suite

SeBS is a diverse suite of FaaS benchmarks that allows an automatic performance
analysis of commercial and open-source serverless platforms. We provide a suite
of [benchmark applications](#benchmark-applications) and [experiments](#experiments)
using them to evaluate different parts of FaaS systems. See [installation instructions](
#installation) to configure SeBS to use selected cloud services and [usage instructions](
#usage) to automatically launch experiments in the cloud!

### Benchmark Applications

Benchmarks are organized into different categories, representing different
types of workloads, from simple web applications up to computationally intensive
video processing, scientific computations and deep learning inference. Each
benchmark comes with **test**, **small** and **large** inputs for automatic invokation.

| Type | Name | Languages |
| ---- | ---- | --------- |
| Webapps | dynamic-html | Python, NodeJS | Dynamic HTML generation. |
| Webapps | uploader | Python, NodeJS | Uploading file to cloud storage. |
| Multimedia | thumbnailer | Python, NodeJS | Resizing user-provided image. |
| Multimedia | video-processing | Python | Adding watermark and gif conversion with ffmpeg. |
| Utilities | compression | Python | Zip compression of storage bucket. |
| Utilities | data-vis | Python | Visualization of DNA data. |
| Inference | image-recognition | Deep learning inference with pytorch and ResNet. |
| Scientific | graph-pagerank | Python | Graph processing example. |
| Scientific | graph-mst | Python | Graph processing example. |
| Scientific | graph-bfs | Python | Graph processing example. |

#### How to add new benchmarks?

Benchmarks follow the naming structure `x.y.z` where x is benchmark group, y is benchmark
ID and z is benchmark version. For examples of implementations, look at `210.thumbnailer`
or `311.compression`. Each benchmark requires the following files:

**config.json** - Defines capabilities and minimum requirements for execution.
```json
{
  "timeout": 60,
  "memory": 256,
  "languages": ["python", "nodejs"]
}
```

**input.py** - Defines the benchmark input and output, including storage buckets (containers)
allocated, and creates a set of inputs used for invocation.
```python
'''
  :return: number of input and output buckets used by the benchmark
'''
def buckets_count():
    return (1, 1)

'''
    Generate test, small and large workload for thumbnailer.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, filepath, key)
    :return: input config for benchmark
'''
def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):

```

Input files for benchmark, e.g. pretrained model and test images for deep learning
inference, will be uploaded to input benchmark in the function `generate_input`.
Output buckets are cleaned after experiments. The function should return input
configuration in form of a dictionary that will be passed to the function at
invocation.

Then place source code and resources in `python` or `nodejs` directories. The entrypoint
should be located in file named `function` and take just one argument:

```python
def handler(event):
```

Configure dependencies in `requirements.txt` and `package.json`. By default, only 
source code is deployed. If you need to use additional resources, e.g. HTML template,
use script `init.sh` (see an example in `110.dynamic-html`).

### Experiments

#### Performance&Cost

TODO: moving experiment code from previous scripts.

#### Cold Start Prediction

TODO: moving experiment code from previous scripts.

#### Scalability

TODO: moving experiment code from previous scripts.

#### Performance Modeling

WiP

### Installation

Requirements:
- Docker (at least 19)
- Python 3.6 with:
    - pip
    - venv
- Standard Linux tools and `zip` installed
... and that should be all.

Run `install.py`. It will create a virtual environment in `sebs-virtualenv`,
install necessary Python dependecies and install third-party dependencies.
Then just activate the newly created Python virtual environment, e.g. with
`source sebs-virtualenv/bin/activate`. Now you can deploy serverless experiments :-)

**Make sure** that your Docker daemon is running and your user has sufficient permissions
to use it. Otherwise you might see a lot of "Connection refused" and "Permission
denied" errors when using **SeBS**.

You can run `tools/build_docker_images.py` to create all necessary Docker images.
to build and run benchmarks. Otherwise they'll be pulled from the Docker Hub repository.

#### AWS

AWS provides one year of free services, including significant amount of compute
time in AWS Lambda. To work with AWS, you need to provide access and secret keys to a role 
with permissions sufficient to manage functions and S3 resources. Additionally,
the account must have `AmazonAPIGatewayAdministrator` permission to set-up automatically
AWS HTTP trigger. Additionally, you
neet to provide Lambda [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
with permissions to Lambda and S3. 

Pass them as environmental variables for the first run. They will be cached for future use.

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Pass lambda role in config JSON, see an example in `config/example.json`.

#### Azure

**temporarily disabled**

Azure provides 200 USD for the first month.
You need to create an account and add a [service principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal) to
enable non-interactive login through CLI. Since this process has [an easy, one-step
CLI solution](https://docs.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest#az-ad-sp-create-for-rbac),
we added a small tool **tools/create_azure_credentials** that uses the interactive web-browser
authentication to login into Azure CLI and create service principal.

```console
Please provide the intended principal name                                                                                                         
XXXXX
Please follow the login instructions to generate credentials...                                                            
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code YYYYYYY to authenticate.

Login succesfull with user {'name': 'ZZZZZZ', 'type': 'user'}                                          
Created service principal http://XXXXX

AZURE_SECRET_APPLICATION_ID = 2a49e1e9-b47d-422b-8d81-461af9e1a61f                                                         
AZURE_SECRET_TENANT = 93ea0232-1fea-4dc8-a174-4ff4a312127a                                                                                                                                     
AZURE_SECRET_PASSWORD = 1u0WtswVq-3gLtPpfJYh_KdUJCWY2J2flg
```

Save these credentials - the password is non retrievable! Provide them to SeBS
through environmental variables and we will create additional resources (storage account, resource group)
to deploy functions.

### Usage

By default, all scripts will create a cache in directory `cache` to handle benchmarks
with necessaries and information on cloud storage resources. Benchmarks will be rebuilt
after change in source code fails (hopefully). If you see in the logs that a cached
entry is still used, pass flag `--update` to force rebuild.

#### Cloud

Use `sebs.py` with options `test`, `publish` and `invoke`. Right now
only a single `test` is supported. Experiments and log querying are coming up now.

Example (please modify the `config/example.json` for your needs).

```
sebs.py --repetitions 1 test_invoke ${benchmark} ${out_dir} ${input_size} config/example.json
```

where `input_size` could be `test`, `small`, `large`. `out_dir` is used to store
local results. Command line options allow to override config (`--deployment`, `--language`).

#### Local

**Might not work currently**

Use `scripts/run_experiments.py` to execute code locally with thelp of minio,
object storage service, running in a container. There are four types of experiments
that can be run: `time`, `memory`, `disk-io` and `papi`. The last one works only
for Python and memory/disk-io are WiP for NodeJS.

If your benchmark fails for some reason, you should see an error directly. If not,
inspect files in `${out_dir}/${experiment}/instance_0/logs`. Use `scripts/clean.sh`
to kill measurement processes if we didn't work.

Containers are usually shutdown after an experiment. The flag `--no-shutdown-containers`
provides a way to leave them alive and inspect the environment for problems.
Simply run `./run.sh ${experiment}.json`.




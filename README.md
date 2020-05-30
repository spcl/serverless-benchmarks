# serverless-benchmarks


The current implementation is a product of a rush to the deadline. Thus, there
some questionable software engineering choices that cannot be fixed now.

Requirements:
- Docker (at least 19 I believe)
- Python 3.6 with:
    - pip
    - venv
... and that should be all.

### Installation

Run `install.sh`. It will create a virtual environment in `sebs-virtualenv`,
install necessary Python dependecies and install third-party dependencies.

Then, run `tools/build_docker_images.py`. It will create all necessary Docker images to build and run
benchmarks. 
On some systems, this command has to be run as root.
To do so:
```
sudo -i
cd project_directory
source sebs-virtualenv/bin/activate
./tools/build_docker_images.py
```

### Work

By default, all scripts will create a cache in directory `cache` to handle benchmarks
with necessaries and information on cloud storage resources. Benchmarks will be rebuilt
after change in source code fails (hopefully). If you see in the logs that a cached
entry is still used, pass flag `--update` to force rebuild.

#### Local

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

#### Cloud

Use `scripts/cloud_experiments.py` with options `publish` and `invoke`. Right now
only a single invoke is supported. Experiments and log querying are coming up now.

### Benchmark configuration

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

Input files for benchmark, e.g. pretrained model and test images for deep learning
inference, will be uploaded to input benchmark according `generate_input`.
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


## Setting up cloud

### Local

Benchmarks can be executed locally without any configuration.

## AWS

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

Pass lambda role in config JSON, see an example in `config/example.json`. Yeah,
that's one of those discrepancies that should be fixed...

## Azure

Azure provides 2000 USD for the first month.
You need to create an account and add [service principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal) to
enable non-interactive login through CLI.

Then, provide principal name

```
AZURE_SECRET_APPLICATION_ID
AZURE_SECRET_TENANT
AZURE_SECRET_PASSWORD
```

We will create storage account and resource group and handle access keys.


# SeBS: Serverless Benchmark Suite

SeBS is a diverse suite of FaaS benchmarks that allows an automatic performance analysis of commercial and open-source serverless platforms. We provide a suite of [benchmark applications](#benchmark-applications) and [experiments](#experiments), and use them to test and evaluate different components of FaaS systems. See the [installation instructions](#installation) to learn how to configure SeBS to use selected cloud services and [usage instructions](#usage) to automatically launch experiments in the cloud!

SeBS provides support for automatic deployment and invocation of benchmarks on  AWS Lambda, Azure Functions, Google Cloud Functions, and a custom, Docker-based local evaluation platform. See the [modularity](#modularity) section to learn how SeBS can be extended with new platforms, benchmarks, and experiments.

## Paper

Our benchmarking paper provides a detailed overview of the benchmark suite, and the experiments we conducted. When using SeBS, please [cite our paper](https://arxiv.org/abs/2012.14132).

```
@misc{copik2020sebs,	
      title={SeBS: A Serverless Benchmark Suite for Function-as-a-Service Computing}, 
      author={Marcin Copik and Grzegorz Kwasniewski and Maciej Besta and Michal Podstawski and Torsten Hoefler},
      year={2020},
      eprint={2012.14132},
      archivePrefix={arXiv},
      primaryClass={cs.DC}
}
```

## Installation

Requirements:
- Docker (at least 19)
- Python 3.6+ with:
    - pip
    - venv
- `libcurl` and its headers must be available on your system to install `pycurl`
- Standard Linux tools and `zip` installed

... and that should be all.

To install the benchmarks with a support for all platforms, use:

```
./install.py --aws --azure --gcp --local
```

It will create a virtual environment in `sebs-virtualenv`, install necessary Python dependecies and install third-party dependencies. Then just activate the newly created Python virtual environment, e.g., with `source sebs-virtualenv/bin/activate`. Now you can deploy serverless experiments :-)

**Make sure** that your Docker daemon is running and your user has sufficient permissions to use it. Otherwise you might see a lot of "Connection refused" and "Permission denied" errors when using SeBS.

You can run `tools/build_docker_images.py` to create all Docker images that are needed to build and run benchmarks. Otherwise they'll be pulled from the Docker Hub repository.

### AWS

AWS provides one year of free services, including significant amount of compute time in AWS Lambda. To work with AWS, you need to provide access and secret keys to a role  with permissions sufficient to manage functions and S3 resources. Additionally, the account must have `AmazonAPIGatewayAdministrator` permission to set-up automatically AWS HTTP trigger. You can provide [role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html) with permissions to access AWS Lambda and S3; otherwise, one will be created automatically. To use your own lambda role, set the name in config JSON - see an example in `config/example.json`.

**Pass the credentials as environmental variables for the first run.** They will be cached for future use.

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

### Azure


Azure provides a free tier for 12 months as well. You need to create an account and add a [service principal](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal) to enable non-interactive login through CLI. Since this process has [an easy, one-step CLI solution](https://docs.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest#az-ad-sp-create-for-rbac), we added a small tool **tools/create_azure_credentials** that uses the interactive web-browser authentication to login into Azure CLI and create service principal.

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

**Save these credentials - the password is non retrievable! Provide them to SeBS through environmental variables** and we will create additional resources (storage account, resource group) to deploy functions. We will create storage account and resource group and handle access keys.

###### Resources

* By default, all functions are allocated in the single resource group.
* Each function has a seperate storage account allocated, following [Azure guidelines](https://docs.microsoft.com/en-us/azure/azure-functions/functions-best-practices#scalability-best-practices).
* All benchmark data is stored in the same storage account.

### GCP

The Google Cloud Free Tier gives free resources to learn about Google Cloud services. It has two parts:

- A 12-month free trial with $300 credit to use with any Google Cloud services.
- Always Free, which provides limited access to many common Google Cloud resources, free of charge.

You need to create an account and add [service account](https://cloud.google.com/iam/docs/service-accounts) to permit operating on storage and functions.

**Pass project name and service account's JSON key path in config JSON, see an example in `config/example.json`**

## Usage

SeBS has three basic commands: `benchmark`, `experiment`, and `local`. For each command you can pass `--verbose` flag to increase the verbosity of the output. By default, all scripts will create a cache in directory `cache` to store code with dependencies and information on allocated cloud resources. Benchmarks will be rebuilt after change in source code fails. To enforce redeployment of code and benchmark input please use flags `--update-code` and `--update-storage`, respectively.

### Benchmark

This command is used to build, deploy, and execute serverless benchmark in cloud. The example below runs the benchmark `110.dynamic-html` on AWS:

```
./sebs.py benchmark invoke 110.dynamic-html test --config config/example.json --deployment aws --verbose
```

To configure your benchmark, change settings in the config file or use commandline options. The full list is available by running `./sebs.py benchmark invoke --help`.

Additionally, we provide a regression option to execute all benchmarks on a given platform. The example below demonstrates how to run the regression suite with `test` input size on AWS.

```
./sebs.py benchmark regression test --config config/example.json --deployment aws
```

### Experiment

This command is used to execute benchmarks described in the paper. The example below runs the experiment **perf-cost**:

```
./sebs.py experiment invoke perf-cost --config config/example.json --deployment aws
```

The configuration specifies that benchmark **110.dynamic-html** is executed 50 times, with 50 concurrent invocations, and both cold and warm invocations are recorded. 

```json
"perf-cost": {
    "benchmark": "110.dynamic-html",
    "experiments": ["cold", "warm"],
    "input-size": "test",
    "repetitions": 50,
    "concurrent-invocations": 50,
    "memory-sizes": [128, 256]
}
```

To download cloud metrics and process the invocations into a .csv file with data, run the process construct

```
./sebs.py experiment process perf-cost --config example.json --deployment aws
```

### Local

In addition to the cloud deployment, we provide an opportunity to launch benchmarks locally with the help of [minio](https://min.io/) storage.

To launch Docker containers serving a selected benchmark, use the following command:

```
./sebs.py local start 110.dynamic-html {input_size} out.json --config config/example.json --deployments 1
```

The output file `out.json` will contain the information on containers deployed and the endpoints that can be used to invoke functions:

```
{
  "functions": [
    {
      "benchmark": "110.dynamic-html",
      "hash": "5ff0657337d17b0cf6156f712f697610",
      "instance_id": "e4797ae01c52ac54bfc22aece1e413130806165eea58c544b2a15c740ec7d75f",
      "name": "110.dynamic-html-python-128",
      "port": 9000,
      "triggers": [],
      "url": "172.17.0.3:9000"
    }
  ],
  "inputs": [
    {
      "random_len": 10,
      "username": "testname"
    }
  ]
}
```

In our example, we can use `curl` to invoke the function with provided input:

```
curl 172.17.0.3:9000 --request POST --data '{"random_len": 10,"username": "testname"}' --header 'Content-Type: application/json'
```

To stop containers, you can use the following command:

```
./sebs.py local stop out.json
```

The stopped containers won't be automatically removed unless the option `--remove-containers` has been passed to the `start` command.

## Benchmark Applications

```markdown
| Type 		   | Benchmark           | Languages          | Description          |
| :---         | :---:               | :---:              | :---:                |
| Webapps      | 110.dynamic-html    | Python, Node.js    | Generate dynamic HTML from a template. |
| Webapps      | 120.uploader.dynamic-html    | Python, Node.js    | Uploader file from provided URL to cloud storage. |
```

For details on benchmark selection, please refer to [our paper](#paper).

## Experiments

TODO :-(

For details on experiments and methodology, please refer to [our paper](#paper).

### Performance&Cost Variability

## Modularity

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

### How to add a new serverless platform?

Implement the interfaces in `sebs/faas/*.py`, and add the new platform to the CLI initialization in `sebs.py` and `sebs/sebs.py`.

### How to add a new experiment?

Implement the interface in `sebs/experiment/experiment.py` and new experiment type to the CLI initialization in `sebs.py` and `sebs/sebs.py`.
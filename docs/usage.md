
SeBS has three basic commands: `benchmark`, `experiment`, and `local`.
For each command you can pass `--verbose` flag to increase the verbosity of the output.
By default, all scripts will create a cache in the directory `cache` to store code with
dependencies and information on allocated cloud resources.
Benchmarks will be rebuilt after a change in source code is detected.
To enforce redeployment of code and benchmark inputs please use flags `--update-code`
and `--update-storage`, respectively.

**Note:** The cache does not support updating the cloud region. If you want to deploy benchmarks
to a new cloud region, then use a new cache directory.

### Benchmark

This command builds, deploys, and executes serverless benchmarks in the cloud.
The example below invokes the benchmark `110.dynamic-html` on AWS via the standard HTTP trigger.

```
./sebs.py benchmark invoke 110.dynamic-html test --config config/example.json --deployment aws --verbose
```

To configure your benchmark, change settings in the config file or use command-line options.
The full list is available by running `./sebs.py benchmark invoke --help`.

### Regression

Additionally, we provide a regression option to execute all benchmarks on a given platform.
The example below demonstrates how to run the regression suite with `test` input size on AWS.

```
./sebs.py benchmark regression test --config config/example.json --deployment aws
```

The regression can be executed on a single benchmark as well:

```
./sebs.py benchmark regression test --config config/example.json --deployment aws --benchmark-name 120.uploader
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

[You can find more details on running experiments and analyzing results in the separate documentation.](experiments.md)

### Local

In addition to the cloud deployment, we provide an opportunity to launch benchmarks locally with the help of [minio](https://min.io/) storage.
This allows us to conduct debugging and a local characterization of the benchmarks.

First, launch a storage instance. The command below is going to deploy a Docker container,
map the container's port to port `9011` on host network, and write storage instance configuration
to file `out_storage.json`

```
./sebs.py storage start minio --port 9011 --output-json out_storage.json
```

Then, we need to update the configuration of `local` deployment with information on the storage 
instance. The `.deployment.local` object in the configuration JSON must contain a new object
`storage`, with the data provided in the `out_storage.json` file. Fortunately, we can achieve
this automatically with a single command by using `jq`:

```
jq --argfile file1 out_storage.json '.deployment.local.storage = $file1 ' config/example.json > config/local_deployment.json
```

The output file will contain a JSON object that should look similar to this one:

```json
"deployment": {
  "name": "local",
  "local": {
    "storage": {
      "address": "172.17.0.2:9000",
      "mapped_port": 9011,
      "access_key": "XXXXX",
      "secret_key": "XXXXX",
      "instance_id": "XXXXX",
      "input_buckets": [],
      "output_buckets": [],
      "type": "minio"
    }
  }
}
```

To launch Docker containers, use the following command - this example launches benchmark `110.dynamic-html` with size `test`:

```
./sebs.py local start 110.dynamic-html test out_benchmark.json --config config/local_deployment.json --deployments 1
```

The output file `out_benchmark.json` will contain the information on containers deployed and the endpoints that can be used to invoke functions:

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
  ],
  "storage: {
    ...
  }
}
```

In our example, we can use `curl` to invoke the function with provided input:

```
curl 172.17.0.3:9000 --request POST --data '{"random_len": 10,"username": "testname"}' --header 'Content-Type: application/json'
```

To stop containers, you can use the following command:

```
./sebs.py local stop out_benchmark.json
./sebs.py storage stop out_storage.json
```

The stopped containers won't be automatically removed unless the option `--remove-containers` has been passed to the `start` command.

#### Memory Measurements

The local backend allows additional continuous measurement of function containers. At the moment,
we support memory measurements. To enable this, pass the following flag to `./sebs.py local start`

```
--measure-interval <val>
```

The value specifies the time between two consecutive measurements. Measurements will be aggregated
and written to a file when calling `./sebs.py local stop <file>`. By default, the data is written
to `memory_stats.json`.


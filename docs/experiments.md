
## Experiments

For details on experiments and methodology, please refer to [the paper](../README.md#publication).

To run experiments, use the `sebs.py benchmark invoke <experiment> -c <config-path>` command.
The configuration of each experiment consists of two parts: deployment and experiment.
The specification of deployment, which is the same for all experiments, is shown below.
Then, each benchmark has its own JSON object containing parameters specific to the experiment.

```json
"experiments": {
  "deployment": "aws",
  "update_code": false,
  "update_storage": false,
  "download_results": false,
  "runtime": {
    "language": "python",
    "version": "3.7"
  },
  "type": "<experiment>",
  ...
}
```

We implemented four types of experiments:
* [Perf-Cost](#perf-cost) evaluates the performance of specified functions and estimates the cost of running them in the cloud. It supports four types of invoking functions and creates timing results involving various parts of the serverless stack.
* [Network Ping-pong](#network-ping-pong) evaluates the network performance and latency profile of the connection between the benchmarking machine and serverless function.
* [Invocation Overhead](#invocation-overhead) estimates the invocation latency by running a clock-drift protocol and comparing timestamps between the benchmarking machine and serverless function.
* [Eviction](#eviction-model) runs functions with various configurations, invokes them after a specified time, and checks if the function is still running in a warm container. The experiment verifies how different parameters affect container eviction.

### Perf-Cost

#### Description

Invokes the given benchmark a selected number of times, measuring the time and cost of invocations.
The experiment supports `cold` and `warm` invocations with a configurable number of concurrent invocations in a single batch.
During the experiment, SeBS continues to invoke the function in batches until it reaches the desired number of cold or warm invocations.
If a cold execution appears during a `warm` experiment or a warm execution happens during a `cold` experiment, then this result is disregarded.

In addition, to accurately measure the overheads of Azure Function Apps, we offer `burst` and `sequential` invocation type that doesn't distinguish
between cold and warm startups. These experiment types help to measure the invocation latencies for platforms where a single sandbox can handle multiple invocation requests. The main difference between both experiments is that the `sequential` experiment invokes functions sequentially, helping to investigate potential scalability issues.

#### Results

These experiments produce four types of timing results. **All measurements are always in microseconds**.
* `exec_time` - the actual time needed to execute the benchmark function, as measured by our lightweight shim.
* `client_time` - the time measured by the SeBS driver on the client machine. This time includes `provider_time`, the overheads of the cloud gateway and FaaS management platform, as well as the data transmission time.
* `connection_time` - the time needed to establish an HTTP connection with the cloud gateway and start data transmission, as reported by cURL ([`PRETRANSFER_TIME`](https://curl.se/libcurl/c/CURLINFO_PRETRANSFER_TIME.html)).
* `provider_time` - the execution time reported by the cloud provider. This time includes `exec_time`, the additional initialization time, and the small overheads of the SeBS shim wrapper.

In addition, on AWS, we provide `billing_time` in milliseconds, rounded up to the nearest integer.
The cloud provider uses this value to determine the cost of running the function.

#### Configuring Benchmark

The file `config/example_perf_cost.json` contains an example of configuration:

```json
"experiments": {
  "type": "perf-cost",
  "perf-cost": {
    "benchmark": "110.dynamic-html",
    "experiments": ["cold", "warm", "burst", "sequential"],
    "input-size": "test",
    "repetitions": 50,
    "concurrent-invocations": 10,
    "memory-sizes": [128, 256]
  }
}
```

The field `benchmark` and `input-size` specifies the benchmark function to be executed. SeBS will invoke the experiment with all configurations specified in `experiments` (see details above). The function will be invoked in batches, each consisting of `concurrent-invocations` instances until SeBS gathers as many results as specified in `repetitions`. While the number of submitted batches usually equals `repetitions/concurrent-invocations`, this can change between experiments as some results might be dropped. For example, a `cold` experiment will ignore all results from a warm container. Furthermore, SeBS will repeat all experiments for each memory configuration provided in `memory-sizes`.

#### Running Benchmark

To execute the benchmark, provide the path to the configuration:

```
sebs.py experiment invoke perf-cost --config config/example_perf_cost.json --output-dir experiments-result
```

At the end of each configuration, you should in the output statistical results summarizing the experiment:

```
[01:37:06.771021] Experiment.PerfCost-04bb Mean 1833.9122199999995 [ms], median 1807.8809999999999 [ms], std 199.52839969009824, CV 10.879931848106574
[01:37:06.771779] Experiment.PerfCost-04bb Parametric CI (Student's t-distribution) 0.95 from 1776.631172772216 to 1891.193267227783, within 3.1234345135550483% of mean
[01:37:06.778019] Experiment.PerfCost-04bb Non-parametric CI 0.95 from 1794.195 to 1819.858, within 0.7097535733823193% of median
[01:37:06.778648] Experiment.PerfCost-04bb Parametric CI (Student's t-distribution) 0.99 from 1757.522715922139 to 1910.30172407786, within 4.165384975615708% of mean
[01:37:06.778731] Experiment.PerfCost-04bb Non-parametric CI 0.99 from 1790.051 to 1821.556, within 0.8713239422285015% of median
```

The full data can be found in the `experiments-result/perf-cost` directory. Each file has a format of `<experiment>_results_<mem-size>.json`, and contains the data for each invocation in a human-readable JSON format. Furthermore, SeBS will produce an additional file, `result.csv`, containing all data in a single tabular file.

#### Postprocessing Results

We support querying cloud logs to locate cloud provider billing data. SeBS achieves this by reading the experiment data obtained in the previous step, finding all invocation IDs, querying cloud log entries, and finding matching data. To process results, run:

```
sebs.py experiment process perf-cost --config config/example_perf_cost.json --output-dir experiments-result
```

For example, on the AWS, you should see the following output for each experiment configuration:

```
[02:16:22.871599] AWS.Config-81b0 Using cached config for AWS
[02:16:23.118470] AWS-696e Waiting for AWS query to complete ...
[02:16:24.449393] AWS-696e Waiting for AWS query to complete ...
[02:16:25.795266] AWS-696e Received 60 entries, found results for 50 out of 50 invocations
```

Afterward, you will find a new file for each experiment configuration called `<experiment>_results_<mem-size>-processed.json`. Each invocation will have a new data entry, containing billing data and time as measured by the cloud provider:

```json
  "billing": {
    "_billed_time": 968,
    "_gb_seconds": 123904,
    "_memory": 128
  }
```

> **Warning**
> Depending on the cloud provider, not all invocations might have corresponding results in cloud logs. Thus, increasing the number of repetitions by roughly 10% is recommended to ensure the desired number of repetitions.

#### Network Ping-pong

Measures the distribution of network latency between benchmark driver and function instance.

Requirement: public IP.

#### Invocation Overhead

The experiment performs the clock drift synchronization protocol to accurately measure the startup time of a function by comparing
benchmark driver and function timestamps.

Requirement: public IP.

#### Eviction Model

**(WiP)** Executes test functions multiple times, with varying size, memory and runtime configurations, to test for how long function instances stay alive.
The result helps to estimate the analytical models describing cold startups.
Currently supported only on AWS.


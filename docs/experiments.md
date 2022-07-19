
## Experiments

For details on experiments and methodology, please refer to [our paper](#paper).

#### Performance & cost

Invokes the given benchmark a selected number of times, measuring the time and cost of invocations.
The experiment supports `cold` and `warm` invocations with a configurable number of concurrent invocations in a single batch.
During the experiment, SeBS continues to invoke the function in batches until it reaches the desired number of cold or warm invocations.
If a cold execution appears during a `warm` experiment or a warm execution happens during a `cold` experiment, then this result is disregarded.

In addition, to accurately measure the overheads of Azure Function Apps, we offer `burst` and `sequential` invocation type that doesn't distinguish
between cold and warm startups. These experiment types help to measure the invocation latencies for platforms where a single sandbox can handle multiple invocation requests. The main difference between both experiments is that the `sequential` experiment invokes functions sequentially, helping to investigate potential scalability issues.

These experiments produce three types of timing results:
* `exec_time` - the actual time needed to execute the benchmark function, as measured by our lightweight shim.
* `provider_time` - the execution time reported by the cloud provider. This time includes `exec_time`, the additional initialization time, and the small overheads of SeBS shim wrapper.
* `client_time` - the time as measured by the SeBS driver on the client machine. This time includes `provider_time`, the overheads of the cloud gateway and FaaS management platform, as well as the data transmission time.
* `connection_time` - the time needed to establish an HTTP connection with the cloud gateway and start data transmission, as reported by cURL ([`PRETRANSFER_TIME`](https://curl.se/libcurl/c/CURLINFO_PRETRANSFER_TIME.html)).

#### Network ping-pong

Measures the distribution of network latency between benchmark driver and function instance.

#### Invocation overhead

The experiment performs the clock drift synchronization protocol to accurately measure the startup time of a function by comparing
benchmark driver and function timestamps.

#### Eviction model

**(WiP)** Executes test functions multiple times, with varying size, memory and runtime configurations, to test for how long function instances stay alive.
The result helps to estimate the analytical models describing cold startups.
Currently supported only on AWS.

#### Communication Channels

**(WiP)**


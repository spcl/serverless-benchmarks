
## Experiments

For details on experiments and methodology, please refer to [our paper](#paper).

#### Performance & cost

Invokes given benchmark a selected number of times, measuring the time and cost of invocations.
Supports `cold` and `warm` invocations with a selected number of concurrent invocations.
In addition, to accurately measure the overheads of Azure Function Apps, we offer `burst` and `sequential` invocation type that doesn't distinguish
between cold and warm startups.

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


## Workflows

### Installation

SeBS makes use of [redis](https://redis.io) in order to make reliable and accurate measurements during the execution of workflows. Ideally, the redis instance should be deployed in the same cloud region such that the write latency is minimal.
Because not all platforms allow connections from a workflow execution to a VPC cache, it proved to be easiest to just deploy a VM and have that machine host redis. Make sure to open port `6379` and admit connections in your VPC accordingly. Redis can be hosted as follows:
```bash
docker run --network=host --name redis -d redis redis-server --save 60 1 --loglevel warning --requirepass {yourpassword}
```

### Usage

To execute a workflow, the host address and password of the redis instance must be given as part of the config file for the respective platform:

```json
"resources": {
  "redis": {
    "host": "1.1.1.1",
    "password": "yourpassword"
  }
}
```

Our workflow benchmarks are provided in the benchmarks folder (benchmarks/600.workflows). To execute a given workflow, use the following command, with "library" triggers for Azure and "http" for AWS and GCP:

```
./sebs.py benchmark workflow {workflow-name} --config {path/to/config.json} --deployment {platform-name} --verbose {input-size} --trigger {library|http} --repetitions 1
```

### Definition

Workflows have been adopted by all major cloud providers, but their implementations are significantly different in capabilities, differing not only in APIs and syntax provided, but also in programming models. We define a workflow model based on Petri Nets, and define workflows using a JSON syntax. The general structure of a workflow definition looks like this:

```json
{
    "root": "first_state",
    "states": {
    }
}
```

`root` defines the initial state to start the workflow from, while `states` holds a dictionary of `(name, state)` tuples. The following state types are supported.

#### Task

A task state is the most basic state: it executes a serverless function.

```json
{
    "type": "task",
    "func_name": "compute",
    "next": "postprocess_compute"
},
```

`func_name` is the name of the file in the benchmark directory, `next` sets the state with which to follow.


#### Map

A map state takes a list as input and processes each element in parallel using the given functions:

```json
{
"type": "map",
"array": "customers",
"root": "shorten",
"next": "list_emails",
"states": { 
  "shorten": {
    "type": "task",
    "func_name": "short"
  } 
}
} 
```

`array` defines the list to be processed, while `root` defines which of the functions given in `states` should be called first. `func_name` is the name of the file in the benchmark directory. In contrast to a `task`'s function, this one receives only an element of the given array, not the entire running variable. Other fields required from the running variable can be given using the `common_params` entry. 

#### Loop

The loop phase is similar to map but traverses the given input array sequentially. Thus, loop encodes tasks that cannot be parallelized due to existing dependencies.

#### Repeat

A repeat phase executes a function a given number of times. This syntactic sugar eases modeling a chain of tasks.

```json
{
"type": "repeat",
"func_name": "process",
"count": 10
}
```

#### Switch

A switch state makes it possible to encode basic control flow.

```json
{
    "type": "switch",
    "cases": [
        {
            "var": "people.number",
            "op": "<",
            "val": 10,
            "next": "few_people"
        },
        {
            "var": "people.number",
            "op": ">=",
            "val": 10,
            "next": "many_people"
        }
    ],
    "default": "few_people"
}
```

This state transcribes to the following Python expression:
```python
if people.number < 10:
    few_people()
elif people.number >= 10:
    many_people()
else:
    few_people()
```

#### Parallel

This higher-level phase corresponds to a parallel routing and executes sub-workflows, consisting of any of the phases, concurrently. The sub-workflows can consist of any of the phases presented. All sub-workflows receive the complete output of the previous phase as input. The outputs of the sub-workflows are merged after all functions have completed execution. 

```json
{
"type": "parallel",
"parallel_functions": [
  {
    "root": "compute",
    "states": {
      "compute": {
        "type": "task",
        "func_name": "compute"
      }
    }
  },
  {
    "root": "sort",
    "states": {
      "sort": {
        "type": "task",
        "func_name": "sort"
      }
    }
  }
],
"next": "frequency_and_overlap"
}
```

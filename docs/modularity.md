
## Modularity

In this document, we explain how to extends SeBS with new benchmarks and experiments,
and how to support new commercial and open-source FaaS platforms.

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

First, implement the interfaces in `sebs/faas/*.py` - details can be found in the
[design documentation](design.md).
Then, add the new platform to the CLI initialization in
[`sebs.py`](https://github.com/spcl/serverless-benchmarks/blob/master/sebs.py#L89)
and
[`sebs/sebs.py`](https://github.com/spcl/serverless-benchmarks/blob/master/sebs/sebs.py#L82).

### How to add a new experiment?

Implement the interface in `sebs/experiment/experiment.py` and
add the new experiment type to the CLI initialization in
[`sebs/sebs.py`](https://github.com/spcl/serverless-benchmarks/blob/master/sebs/sebs.py#L108).

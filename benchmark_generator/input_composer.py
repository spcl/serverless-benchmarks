import uuid

def compose(config):
    benchmarks_list = {benchmark for (benchmark, benchmark_config) in config}

    input_dict = {}
    print(config)
    for (benchmark, benchmark_config) in config:
        if benchmark == "function_input" and "input_size" in benchmark_config.keys():
            # input size is measured by number of elements
            for i in range(int(benchmark_config["input_size"])):
                input_dict[str(uuid.uuid1())] = 100
    
    # add needed values

    # generate code
    code = ""
    code += "input_dict = " + str(input_dict) + "\n"

    if "storage" in benchmarks_list:
        code += """def buckets_count():
    return (0, 1)\n"""
    else:
        code += """def buckets_count():
    return (0, 0)\n"""

    if "storage" in benchmarks_list:
        code += """def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    input_dict = {'bucket': {}}
    input_dict['bucket']['output'] = output_buckets[0]
    return input_dict """
    else:  
        code += """def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return input_dict """
    return code

        
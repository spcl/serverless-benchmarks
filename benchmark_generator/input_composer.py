import uuid

def compose(config):
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


    code += """def buckets_count():
    return (0, 0)\n"""


    code += """def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return input_dict """
    return code

        
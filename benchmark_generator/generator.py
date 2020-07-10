import sys
import json
import code_composer
import requirements_composer
import input_composer
import os

if len(sys.argv) < 2:
    print("Missing argument, path to config")

with open(sys.argv[1]) as config_file:
    total_config = json.load(config_file)

if total_config["language"] == "python":
    config = total_config["config"]

    # Generate directory for benchmark
    path_to_benchmark = "./../benchmarks/600.generated/620.generated/python"
    if not os.path.exists(path_to_benchmark):
        os.makedirs(path_to_benchmark)

    # Push code to benchmarks/600.generated/620.generated/python/function.py

    with open(path_to_benchmark + "/function.py", "w+") as code_file:
        code = code_composer.compose(config, "python")
        code_file.write(code)

    # Push requirements to benchmarks/600.generated/620.generated/python/requirements.txt
    with open(path_to_benchmark + "/requirements.txt", "w+") as requirements_file:
        requirements = requirements_composer.compose(config)
        print("Req: " + requirements)
        requirements_file.write(requirements)

elif total_config["language"] == "async_nodejs":
    config = total_config["config"]

    # Generate directory for benchmark
    path_to_benchmark = "./../benchmarks/600.generated/620.generated/nodejs"
    if not os.path.exists(path_to_benchmark):
        os.makedirs(path_to_benchmark)

    # Push code to benchmarks/600.generated/620.generated/nodejs/function.js

    with open(path_to_benchmark + "/function.js", "w+") as code_file:
        code = code_composer.compose(config, "async_nodejs")
        code_file.write(code)

    # Push requirements to benchmarks/600.generated/620.generated/nodejs/package.json
    with open(path_to_benchmark + "/package.json", "w+") as requirements_file:
        requirements = requirements_composer.compose(config, "async_nodejs")
        print("Req: " + requirements)
        requirements_file.write(requirements)

# Create input.py file
with open(path_to_benchmark + "/../input.py", "w+") as input_file:
    code = input_composer.compose(config)
    input_file.write(code)
import sys
import json
import code_composer
import requirements_composer
import input_composer
import os

if len(sys.argv) < 2:
    print("Missing argument, path to config")

with open(sys.argv[1]) as config_file:
    config = json.load(config_file)

# Generate directory for benchmark
path_to_benchmark = "./../benchmarks/600.generated/610.generated/python"
if not os.path.exists(path_to_benchmark):
    os.makedirs(path_to_benchmark)

# Push code to benchmarks/600.generated/610.generated/python/function.py

with open(path_to_benchmark + "/function.py", "w+") as code_file:
    code = code_composer.compose(config)
    code_file.write(code)

# Push requirements to benchmarks/600.generated/610.generated/python/requirements.txt
with open(path_to_benchmark + "/requirements.txt", "w+") as requirements_file:
    requirements = requirements_composer.compose(config)
    print("Req: " + requirements)
    requirements_file.write(requirements)

# Create input.py file
with open(path_to_benchmark + "/../input.py", "w+") as input_file:
    code = input_composer.compose(config)
    input_file.write(code)
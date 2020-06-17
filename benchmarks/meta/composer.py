import os

def load_benchmark_code(benchmark_name, language="python"):
    current_dir = os.getcwd()
    path_to_code = os.path.join(current_dir, benchmark_name, language, "function.py" if language == "python" else "sth.js")
    with open(path_to_code, "r") as source_file:
        source_code = source_file.read()
        [_, after_test] = source_code.split("#test")
        [_, after_import] = after_test.split("#import")
        [import_part, after_function] = after_import.split("#function")
        [function_part, run_part] = after_function.split("#run")
        return {
            "import": import_part,
            "function": function_part,
            "run": run_part
        }

    

config = [
    ("workload", {
        "iterations": 10000,
        "operator": "-",
        "type": "float32",
        "array_size": 1000
        }
    ),
    ("memory", {
        "size_in_bytes": 1024 * 1024 * 1024
    }),
    ("workload", {
        "iterations": 10000,
        "operator": "-",
        "type": "float32",
        "array_size": 1000
        }
    )
]

code = ""

benchmarks_list = {benchmark for (benchmark, benchmark_config) in config}

# load code of benchmarks
code_maps = {
    benchmark_name: load_benchmark_code(benchmark_name) for benchmark_name in benchmarks_list
}

# add imports
for code_map in code_maps.values():
    code += code_map["import"] + "\n"

#add functions
for code_map in code_maps.values():
    code += code_map["function"] + "\n"

#add invoke of benchmarks
for (benchmark_name, benchmark_config) in config:
    code += "config = " + str(benchmark_config)
    code += code_maps[benchmark_name]["run"]

print(code)
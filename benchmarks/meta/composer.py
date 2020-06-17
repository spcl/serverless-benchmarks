import os

def load_benchmark_code(benchmark_name, language="python"):
    current_dir = os.getcwd()
    path_to_code = os.path.join(current_dir, benchmark_name, language, "function.py" if language == "python" else "sth.js")
    with open()
    

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
code_map = {
    benchmark_name: load_benchmark_code(benchmark_name) for benchmark_name in benchmarks_list
}

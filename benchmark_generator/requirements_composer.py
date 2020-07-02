import os

def load_benchmark_requirements(benchmark_name, language="python"):
    current_dir = os.getcwd()
    path_to_requirements = os.path.join(current_dir, benchmark_name, language, "requirements.txt" if language == "python" else "sth.js")
    if os.path.exists(path_to_requirements) and os.path.isfile(path_to_requirements):
        with open(path_to_requirements, "r") as source_file:
            requirements = source_file.read()
            return requirements
    else:
        print("Path to: " + path_to_requirements + " doenst exist")
        return ""

def compose(config):

    benchmarks_list = {benchmark for (benchmark, benchmark_config) in config}

    requirements_for_all_benchmarks = "" 
    for benchmark_name in benchmarks_list:
        requirements_for_all_benchmarks += "\n" + load_benchmark_requirements(benchmark_name)
    return requirements_for_all_benchmarks


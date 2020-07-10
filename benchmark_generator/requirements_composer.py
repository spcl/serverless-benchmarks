import os
import json

def load_benchmark_requirements(benchmark_name):
    current_dir = os.getcwd()
    path_to_requirements = os.path.join(current_dir, benchmark_name, "python", "requirements.txt")
    if os.path.exists(path_to_requirements) and os.path.isfile(path_to_requirements):
        with open(path_to_requirements, "r") as source_file:
            requirements = source_file.read()
            return requirements
    else:
        print("Path to: " + path_to_requirements + " doenst exist")
        return ""

def prepare_python_file(config):
    benchmarks_list = {benchmark for (benchmark, benchmark_config) in config}

    requirements_for_all_benchmarks = "" 
    for benchmark_name in benchmarks_list:
        requirements_for_all_benchmarks += "\n" + load_benchmark_requirements(benchmark_name)
    return requirements_for_all_benchmarks

def load_benchmark_dependencies(benchmark_name, language):
    current_dir = os.getcwd()
    path_to_dependencies = os.path.join(current_dir, benchmark_name, language, "package.json")
    if os.path.exists(path_to_dependencies) and os.path.isfile(path_to_dependencies):
        with open(path_to_dependencies, "r") as json_file:
            package_json = json.load(json_file)
            return (package_json["dependencies"], package_json["devDependencies"])
    else:
        print("Path to: " + path_to_dependencies + " doenst exist")
        return ({}, {})

def prepare_nodejs_file(config, language):
    benchmarks_list = {benchmark for (benchmark, benchmark_config) in config}

    dependencies_list = [load_benchmark_dependencies(benchmark_name, language) for benchmark_name in benchmarks_list]

    dependencies = {}
    dev_dependencies = {}
    for dependency, dev_dependency in dependencies_list:
        dependencies.update(dependency)
        dev_dependencies.update(dev_dependency)
    
    return json.dumps({
        "name": "generated_benchmark",
        "version": "1.0.0",
        "description": "",
        "author": "",
        "license": "",
        "dependencies": dependencies,
        "devDependencies": dev_dependencies
    })


def compose(config, language):
    if language == "python":
        return prepare_python_file(config)
    else:
        return prepare_nodejs_file(config, language)
    


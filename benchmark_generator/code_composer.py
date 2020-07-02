import os

def load_benchmark_code(benchmark_name, language="python"):
    current_dir = os.getcwd()
    path_to_code = os.path.join(current_dir, benchmark_name, language, "function.py" if language == "python" else "sth.js")
    if os.path.exists(path_to_code):
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
    return {
                "import": "",
                "function": "",
                "run": ""
            }

def intend(body):
    new_body = ""
    for line in body.splitlines():
        new_body += "\n\t" + line
    return new_body

def compose(config):

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

    code += "\ndef handler(event):\n"
    #add invoke of benchmarks
    handler_function = "result = {}\n"
    for (number, (benchmark_name, benchmark_config)) in enumerate(config):
        handler_function += "\nnumber = " + str(number) + "\n"
        handler_function += "config = " + str(benchmark_config) + "\n"
        handler_function += code_maps[benchmark_name]["run"]

    handler_function += """\nresult['result'] = 100\nreturn {'result': result }"""     # dummy result, different doesn't work

    code += intend(handler_function)

    return code

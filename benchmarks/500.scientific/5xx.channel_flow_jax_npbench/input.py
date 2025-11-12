size_generators = {
    "test": { "ny": 61, "nx": 61, "nit": 5,  "rho": 1.0, "nu": 0.1, "F": 1.0 },
    "small": { "ny": 121, "nx": 121, "nit": 10,  "rho": 1.0, "nu": 0.1, "F": 1.0 },
    "large": { "ny": 201, "nx": 201, "nit": 20,  "rho": 1.0, "nu": 0.1, "F": 1.0 },
}

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func, nosql_func):
    return { 'size': size_generators[size] }
 
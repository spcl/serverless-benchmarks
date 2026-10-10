# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

import os
import re
import uuid
import io

size_generators = {
    "test" : (1),
    "small": (5),
    "small-10": (10),
    "large": (10),
}

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_buckets, output_buckets, upload_func, nosql_func):
    files = ["ALL.chr21.1250.vcf", "ALL.chr21.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf", "columns.txt", "AFR", "ALL", "AMR", "EAS", "EUR", "GBR", "SAS"]
    for name in files:
        #if name != "ALL.chr21.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf":
        path = os.path.join(data_dir, name)
        upload_func(0, name, path)

    num_individuals_jobs = size_generators[size]

    blobs = []
    start_bytes = 0
    with open(os.path.join(data_dir, files[0]), "r") as f:
        content = f.readlines()
        #TODO potentially change if input file with different number of lines is to be processed.
        range_per_job = 1250 / num_individuals_jobs
        for i in range(0, num_individuals_jobs):
            #actually split file; return it afterwards. see e.g. split.py in 660.map-reduce.
            #regex = re.compile('(?!#)')
            start = i * range_per_job
            end = i * range_per_job + range_per_job
            #print("start: ", start, "end: ", end, "range_per_job: ", range_per_job, "num_individuals_jobs: ", num_individuals_jobs)
            #data = list(filter(regex.match, content[int(start):int(end)]))
            data = content[int(start):int(end)]
            #name with start and end lines is not needed as all individuals jobs can just read their entire file.
            name = str(uuid.uuid4())[:8]

            upload_data = io.BytesIO()
            upload_data.writelines((val).encode("utf-8") for val in data)
            upload_data.seek(0)
            #name = client.upload_stream(output_bucket, name, upload_data)
            #TODO keep track of start + stop bytes and return them.
            nbytes = upload_data.getbuffer().nbytes

            output = {
                "start_bytes": start_bytes,
                "end_bytes": start_bytes + nbytes - 1
            }

            blobs.append(output)
            start_bytes += nbytes

    return {
        "bucket": output_buckets[0],
        "blob": blobs,
        "individuals_file": files[0],
        "benchmark_bucket": benchmarks_bucket,
        "columns_bucket": input_buckets[0],
        "columns": files[2],
        "populations": files[3:9],
        "sifting_input": files[1],
    }


def validate_output(data_dir: str | None, input_config: dict, output: dict, language: str, storage = None) -> str | None:
    if output is None:
        return "Output is None"

    if not isinstance(output, dict):
        return f"Expected output to be a dict, got {type(output).__name__}"

    # Real output structure:
    # {
    #   "mutation_overlap": {"sifting": {"populations": [{"output_mutation_overlap": "..."}...]}},
    #   "frequency": {"sifting": {"populations": [{"output_frequency": "..."}...]}}
    # }
    for branch in ("mutation_overlap", "frequency"):
        if branch not in output:
            return f"Output missing '{branch}' key, got keys: {list(output.keys())}"
        sifting = output[branch].get("sifting")
        if not isinstance(sifting, dict):
            return f"output['{branch}']['sifting'] is not a dict"
        pops = sifting.get("populations")
        if not isinstance(pops, list) or len(pops) == 0:
            return f"output['{branch}']['sifting']['populations'] is not a non-empty list"

    input_populations = input_config.get("populations", [])
    expected_key = {"mutation_overlap": "output_mutation_overlap", "frequency": "output_frequency"}
    # Output filename patterns: chr21-{POP}.tar.*gz for mutation_overlap, chr21-{POP}-freq.tar.*gz for frequency
    filename_patterns = {"mutation_overlap": "chr21-{pop}", "frequency": "chr21-{pop}-freq"}

    for branch, key in expected_key.items():
        pops = output[branch]["sifting"]["populations"]

        # Population count should match input
        if input_populations and len(pops) != len(input_populations):
            return (
                f"output['{branch}']['sifting']['populations'] has {len(pops)} entries, "
                f"expected {len(input_populations)} (one per input population)"
            )

        for i, p in enumerate(pops):
            if not isinstance(p, dict):
                return f"output['{branch}']['sifting']['populations'][{i}] is not a dict"
            if key not in p:
                return f"output['{branch}']['sifting']['populations'][{i}] missing '{key}'"

            filename = p[key]
            if not isinstance(filename, str) or not filename:
                return f"output['{branch}']['sifting']['populations'][{i}]['{key}'] is not a non-empty string"

            if not filename.endswith(".gz"):
                return f"output['{branch}']['sifting']['populations'][{i}]['{key}'] should end with .gz, got '{filename}'"

            # Filename should contain the population name
            if input_populations:
                pop_name = input_populations[i] if i < len(input_populations) else None
                pattern_prefix = filename_patterns[branch].format(pop=pop_name) if pop_name else None
                if pattern_prefix and pattern_prefix.lower() not in filename.lower():
                    return (
                        f"output['{branch}']['sifting']['populations'][{i}]['{key}'] = '{filename}' "
                        f"does not contain expected population pattern '{pattern_prefix}'"
                    )

    return None

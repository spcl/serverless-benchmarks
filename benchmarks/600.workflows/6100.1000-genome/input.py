import os

size_generators = {
    "test" : (1),
    "small": (4),
    "large": (10),
}

def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    #TODO replace individuals input with larger file. 
    files = ["ALL.chr21.300.vcf", "ALL.chr21.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf", "columns.txt", "AFR", "ALL", "AMR", "EAS", "EUR", "GBR", "SAS"]
    for name in files:
        if name != "ALL.chr21.phase3_shapeit2_mvncall_integrated_v5.20130502.sites.annotation.vcf":
            path = os.path.join(data_dir, name)
            upload_func(0, name, path)

    num_individuals_jobs = size_generators[size]
    return {
        "individuals_input": files[0],
        "sifting_input": files[1],
        "columns": files[2],
        "num_individuals_jobs": num_individuals_jobs,
        "output_bucket": output_buckets[0],
        "input_bucket": input_buckets[0],
        "populations": files[3:9]
    }
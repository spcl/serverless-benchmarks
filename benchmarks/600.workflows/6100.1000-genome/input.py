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

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
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
        "columns_bucket": input_buckets[0],
        "columns": files[2],
        "populations": files[3:9],
        "sifting_input": files[1],
    }

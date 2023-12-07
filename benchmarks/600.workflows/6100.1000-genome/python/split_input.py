import os
import io
import uuid
import re
from . import storage

def handler(event):
    individuals_bucket = event["input_bucket"]
    individuals_input = event["individuals_input"]
    individuals_path = os.path.join("/tmp", "individuals_input.vcf")
    
    output_bucket = event["output_bucket"]

    client = storage.storage.get_instance()
    client.download(individuals_bucket, individuals_input, individuals_path)

    num_individuals_jobs = int(event["num_individuals_jobs"])

    blobs = []
    with open(individuals_path, "r") as f:
        content = f.readlines()
        #TODO potentially change if input file with different number of lines is to be processed.
        range_per_job = 300 / num_individuals_jobs
        for i in range(0, num_individuals_jobs):
            #actually split file; return it afterwards. see e.g. split.py in 660.map-reduce.
            regex = re.compile('(?!#)')
            start = i * range_per_job
            end = i * range_per_job + range_per_job
            print("start: ", start, "end: ", end, "range_per_job: ", range_per_job, "num_individuals_jobs: ", num_individuals_jobs)
            data = list(filter(regex.match, content[int(start):int(end)]))
            #name with start and end lines is not needed as all individuals jobs can just read their entire file. 
            name = str(uuid.uuid4())[:8]
            
            upload_data = io.BytesIO()
            upload_data.writelines((val).encode("utf-8") for val in data)
            upload_data.seek(0)

            name = client.upload_stream(output_bucket, name, upload_data)
            blobs.append(name)
    os.remove(individuals_path)

    prefix = str(uuid.uuid4())[:8]
    return {
        "bucket": output_bucket,
        "blob": blobs,
        #"prefix": prefix,
        "columns_bucket": event["input_bucket"],
        "columns": event["columns"],
        "populations": event["populations"],
        "sifting_input": event["sifting_input"]
    }

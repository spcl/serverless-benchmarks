import os
from . import storage
import time
import tarfile
import tempfile
import shutil

def handler(event):

  individuals_output_bucket = event["bucket"]
  filenames = []
  for elem in event["blob"]: 
      filenames.append(elem["individuals_output"])
  
  #download files
  client = storage.storage.get_instance()
  for file in filenames:
      client.download(individuals_output_bucket, file, os.path.join('/tmp', file))

  #call merging with c and directories.
  outputfile_name, outputfile = merging(21, filenames)
  #upload outputfile
  outputfile_name = client.upload(individuals_output_bucket, outputfile_name, outputfile)

  return {
      "merge_outputfile_name": outputfile_name
  }

def compress(archive, input_dir):
    with tarfile.open(archive, "w:gz") as f:
        f.add(input_dir, arcname="")

def extract_all(archive, output_dir):
    with tarfile.open(archive, "r:*") as f:
        f.extractall(output_dir)
        flist = f.getnames()
        if flist[0] == '':
            flist = flist[1:]
        return flist

def readfile(filename):
    with open(filename, 'r') as f:
        content = f.readlines()
    return content

def writefile(filename, content):
    with open(filename, 'w') as f:
        f.writelines(content)

def merging(c, tar_files):
    tic = time.perf_counter()


    merged_dir = "merged_chr{}".format(c)
    merged_dir = os.path.join("/tmp", merged_dir)
    os.makedirs(merged_dir, exist_ok=True)

    data = {}

    for tar in tar_files:
        tic_iter = time.perf_counter()
        os.makedirs("/tmp/temp_dir", exist_ok=True)
        with tempfile.TemporaryDirectory(dir="/tmp/temp_dir") as temp_dir:
            for filename in extract_all(os.path.join("/tmp", tar), temp_dir):
                content = readfile(os.path.join(temp_dir, filename))
                if filename in data:
                    data[filename] += content
                else:
                    data[filename] = content

    
    for filename,content in data.items():
        writefile(os.path.join(merged_dir, filename), content)
    
    outputfile_name = "chr{}n.tar.gz".format(c)
    outputfile = os.path.join("/tmp", outputfile_name)

    compress(outputfile, merged_dir)

    # Cleaning temporary files
    try:
        shutil.rmtree(merged_dir)
    except OSError as e:
        print("Error: %s : %s" % (merged_dir, e.strerror))

    return outputfile_name, outputfile
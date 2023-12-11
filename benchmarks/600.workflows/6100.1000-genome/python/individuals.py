import os
import uuid
import tarfile
import shutil
import re
from . import storage

client = storage.storage.get_instance()

def compress(output, input_dir):
    with tarfile.open(output, "w:gz") as file:
        file.add(input_dir, arcname=os.path.basename(input_dir))

def readfile(file):
    with open(file, 'r') as f:
        content = f.readlines()
    return content

def handler(event):
    print("event: ", event)

    individuals_bucket = event["bucket"]
    individuals_input = event["individuals_file"]

    start_bytes = event["array_element"]["start_bytes"]
    end_bytes = event["array_element"]["end_bytes"]

    columns = event["columns"]
    columns_bucket = event["columns_bucket"]
    columns_path = os.path.join("/tmp", "columns.txt")
    
    client = storage.storage.get_instance()
    client.download(columns_bucket, columns, columns_path)
    data = client.download_within_range(columns_bucket, individuals_input, start_bytes, end_bytes)

    ndir = 'chr{}n-{}/'.format(21, individuals_input)
    ndir = os.path.join("/tmp", ndir)
    os.makedirs(ndir, exist_ok=True)

    regex = re.compile('(?!#)')
    data = data.split("\n")
    data = list(filter(lambda line: regex.match(line) and line != "", data))

    chrp_data = {}
    columndata = readfile(columns_path)[0].rstrip('\n').split('\t')

    start_data = 9  # where the real data start, the first 0|1, 1|1, 1|0 or 0|0
    # position of the last element (normally equals to len(data[0].split(' '))
    #end_data = 2504
    end_data = len(columndata) - start_data
    print("== Number of columns {}".format(end_data))

    for i in range(0, end_data):
        col = i + start_data
        name = columndata[col]

        filename = "{}/chr{}.{}".format(ndir, "21", name)
        #print("=== Writing file {}".format(filename), end=" => ")
        chrp_data[i] = []

        with open(filename, 'w') as f:
            for line in data:
                #print("line: ", line)
                #print(i, line.split('\t'))
                #print("line: ", line, "col: ", col)
                first = line.split('\t')[col]  # first =`echo $l | cut -d -f$i`
                #second =`echo $l | cut -d -f 2, 3, 4, 5, 8 --output-delimiter = '   '`
                second = line.split('\t')[0:8]
                # We select the one we want
                second = [elem for id, elem in enumerate(second) if id in [1, 2, 3, 4, 7]]
                af_value = second[4].split(';')[8].split('=')[1]
                # We replace with AF_Value
                second[4] = af_value
                try:
                    if ',' in af_value:
                        # We only keep the first value if more than one (that's what awk is doing)
                        af_value = float(af_value.split(',')[0])
                    else:
                        af_value = float(af_value)

                    elem = first.split('|')
                    # We skip some lines that do not meet these conditions
                    if af_value >= 0.5 and elem[0] == '0':
                        chrp_data[i].append(second)
                    elif af_value < 0.5 and elem[0] == '1':
                        chrp_data[i].append(second)
                    else:
                        continue

                    f.write("{0}        {1}    {2}    {3}    {4}\n".format(
                        second[0], second[1], second[2], second[3], second[4])
                    )
                except ValueError:
                    continue

        print("processed")

    outputfile = "chr{}n-{}.tar.gz".format(21, individuals_input)
    print("== Done. Zipping {} files into {}.".format(end_data, outputfile))

    # tar -zcf .. /$outputfile .
    compress(os.path.join("/tmp/", outputfile), ndir)
    outputfile_name = client.upload(individuals_bucket, outputfile, os.path.join("/tmp/", outputfile))

    # Cleaning temporary files
    try:
        shutil.rmtree(ndir)
    except OSError as e:
        print("Error: %s : %s" % (ndir, e.strerror))

    return {
        "individuals_output": outputfile_name,
    }
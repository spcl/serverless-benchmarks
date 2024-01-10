import os
import re
from . import storage
import subprocess

def readfile(file):
    with open(file, 'r') as f:
        content = f.readlines()
    return content

def handler(event):

  input_bucket = event["columns_bucket"]
  input_filename = event["sifting_input"]
  inputfile = os.path.join("/tmp", "sifting_file.vcf")

  output_bucket = event["bucket"]

  client = storage.storage.get_instance()
  client.download(input_bucket, input_filename, inputfile)

  #c is the chromosome number - doesn't matter here. 
  c = 21
  final_name = 'sifted.SIFT.chr{}.txt'.format(c)
  final = os.path.join("/tmp", final_name)

  rawdata = readfile(inputfile)


  r1 = re.compile('.*(#).*')
  header = len(list(filter(r1.match, rawdata[:1000])))

  siftfile = 'SIFT.chr{}.vcf'.format(c)
  siftfile = os.path.join("/tmp", siftfile)
  with open(siftfile, 'w') as f:
      subprocess.run(["grep -n \"deleterious\|tolerated\" {}".format(inputfile)], shell=True, stdout=f)

  data_temp = readfile(siftfile)

  r3 = re.compile('.*(rs).*')
  data = list(filter(r3.match, data_temp))


  with open(final, 'w') as f:
      for l in data:
          line = str(int(l.split('\t')[0].split(':')[0]) - int(header))
          id = l.split('\t')[2]

          sifts = l.split('\t')[7].split('|')
          sifts = sifts[4] + ' ' + sifts[16] + ' ' + sifts[17]
          sifts = sifts.replace('(', ' ').replace(')', '')
          
          temp = (line + ' ' + id + ' ' + sifts).split(' ')

          if temp[3] == '' or temp[4] == '':
              f.write("{} {} {}\n".format(temp[0], temp[1], temp[2]))
          elif temp[5] == '':
              f.write("{} {} {} {}\n".format(temp[0], temp[1], temp[2], temp[4]))
          else:
              f.write("{} {} {} {} {}\n".format(temp[0], temp[1], temp[2], temp[4], temp[6]))

  os.remove(siftfile)

  final_name = client.upload(output_bucket, final_name, final)

  return {
      "output_bucket": output_bucket,
      "output_sifting": final_name,
      "populations": event["populations"],
      "input_bucket": input_bucket
  }
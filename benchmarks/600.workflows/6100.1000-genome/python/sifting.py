import os
import re
from . import storage
import subprocess

def readfile(file):
    with open(file, 'r') as f:
        content = f.readlines()
    return content

def handler(event):
  #sifting stuff is the same for every list entry - just take the first element. 
  #event = event["blob"][0]

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

  print("= Taking columns from {}".format(inputfile))
  print("== Filtering over {} lines".format(len(rawdata)))

  r1 = re.compile('.*(#).*')
  header = len(list(filter(r1.match, rawdata[:1000])))
  print("== Header found -> {}".format(header))

  siftfile = 'SIFT.chr{}.vcf'.format(c)
  siftfile = os.path.join("/tmp", siftfile)
  with open(siftfile, 'w') as f:
      subprocess.run(["grep -n \"deleterious\|tolerated\" {}".format(inputfile)], shell=True, stdout=f)

  data_temp = readfile(siftfile)

  r3 = re.compile('.*(rs).*')
  data = list(filter(r3.match, data_temp))

  print("== Starting processing {} lines".format(len(data)))

  with open(final, 'w') as f:
      for l in data:
          # awk '{print $1}' $siftfile | awk -F ":" '{print $1-'$header'}' > $lines #.txt
          line = str(int(l.split('\t')[0].split(':')[0]) - int(header))
          # awk '{print $3}' $siftfile > $ids #.txt
          id = l.split('\t')[2]

          # awk '{print $8}' $siftfile > $info  # .txt
          # awk - F "|" '{print $5"\t"$17"\t"$18}' $info | sed 's/(/\t/g' | sed 's/)//g' > $sifts
          sifts = l.split('\t')[7].split('|')
          sifts = sifts[4] + ' ' + sifts[16] + ' ' + sifts[17]
          sifts = sifts.replace('(', ' ').replace(')', '')
          
          # pr -m -t -s ' ' $lines $ids $sifts | gawk '{print $1,$2,$3,$5,$7}' > $final
          temp = (line + ' ' + id + ' ' + sifts).split(' ')

          if temp[3] == '' or temp[4] == '':
              f.write("{} {} {}\n".format(temp[0], temp[1], temp[2]))
          elif temp[5] == '':
              f.write("{} {} {} {}\n".format(temp[0], temp[1], temp[2], temp[4]))
          else:
              f.write("{} {} {} {} {}\n".format(temp[0], temp[1], temp[2], temp[4], temp[6]))

  os.remove(siftfile)
  print("= Line, id, ENSG id, SIFT, and phenotype printed to {}.".format(final))

  final_name = client.upload(output_bucket, final_name, final)

  return {
      "output_bucket": output_bucket,
      "output_sifting": final_name,
      "populations": event["populations"],
      "input_bucket": input_bucket
  }
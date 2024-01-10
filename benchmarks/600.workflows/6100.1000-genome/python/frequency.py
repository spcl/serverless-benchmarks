import time

tic = time.perf_counter()
import numpy as np
from random import sample
import os.path
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import collections
from collections import Counter

import os
from . import storage


class ReadData:
    def read_names(self, POP, pop_dir, columns_file):
        tic = time.perf_counter()
        namefile = pop_dir + POP
        f = open(namefile, 'r')
        text = f.read()
        f.close()
        text = text.split()
        all_ids = text[0:]
        file = columns_file
        f = open(file, 'r')
        text = f.read()
        f.close()
        genome_ids = text.split()

        ids = list(set(all_ids) & set(genome_ids))
        return ids

    def read_rs_numbers(self, siftfile, SIFT):
        ## NB This file is in the format of:
        ## line number, rs number, ENSG number, SIFT, Phenotype
        tic = time.perf_counter()
        rs_numbers = []
        variations = {}
        map_variations = {}
        all_variations = []
        sift_file = open(siftfile, 'r')
        for item in sift_file:
            item = item.split()
            if len(item) > 2:
                rs_numbers.append(item[1])
                map_variations[item[1]] = item[2]
                variations[item[0]] = item[2]

        return rs_numbers, map_variations

    def read_individuals(self, ids, rs_numbers, data_dir, chrom, individuals_merge_filename):
        tic = time.perf_counter()
        mutation_index_array = []
        for name in ids:
            filename = data_dir + individuals_merge_filename + '/' + chrom + '.' + name
            f = open(filename, 'r')
            text = []
            for item in f:
                item = item.split()
                try:
                    text.append(item[1])
                except IndexError as e:
                    print("ERROR({}): while reading {}: (item: {})".format(str(e), filename, item))        
            sifted_mutations = list(set(rs_numbers).intersection(text))
            mutation_index_array.append(sifted_mutations)

        return mutation_index_array


class Results:

    def overlap_ind(self, ids, mutation_index_array, n_runs, n_indiv):
        n_p = len(mutation_index_array)
        tic = time.perf_counter()
        list_p = np.linspace(0, n_p - 1, n_p).astype(int)
        mutation_overlap = []
        random_indiv = []
        for run in range(n_runs):
            randomized_list = sample(list(list_p), n_p)
            result = Counter()
            r_ids = []
            for pq in range(n_indiv):
                if 2 * pq >= len(randomized_list):
                    break
                b_multiset = collections.Counter(mutation_index_array[randomized_list[2 * pq]])
                r_ids.append(ids[randomized_list[2 * pq]])
                result = result + b_multiset
            random_indiv.append(r_ids)
            mutation_overlap.append(result)
        return mutation_overlap, random_indiv

    def histogram_overlap(self, mutation_overlap, n_runs):
        tic = time.perf_counter()
        histogram_overlap = []
        for run in range(n_runs):
            final_counts = [count for item, count in mutation_overlap[run].items()]
            histogram_overlap.append(collections.Counter(final_counts))
        return histogram_overlap


class PlotData:

    def plot_histogram_overlap(self, POP, histogram_overlap, outputFile, n_runs):
        tic = time.perf_counter()
        for run in range(n_runs):
            output = outputFile + str(run) + '.png'
            final_counts = [count for item, count in histogram_overlap[run].items()]
            N = len(final_counts)
            x = range(N)
            width = 1 / 1.5
            bar1 = plt.bar(x, final_counts, width, color="grey")
            plt.ylabel('Mutations')
            plt.xlabel('Individuals')
            plt.xticks(np.arange(1, N + 1))
            plt.savefig(output)
            plt.close()


class WriteData:

    def write_histogram_overlap(self, histogram_overlapfile, histogram_overlap, n_runs, n_indiv):
        tic = time.perf_counter()
        for run in range(n_runs):
            overlapfile = histogram_overlapfile + str(run) + '.txt'
            f = open(overlapfile, 'w')
            f.write('Number Individuals - Number Mutations  \n')
            for i in range(1, n_indiv + 1):
                if i in histogram_overlap[run]:
                    f.write(str(i) + '-' + str(histogram_overlap[run][i]) + '\n')
                else:
                    f.write(str(i) + '-' + str(0) + '\n')
            f.close()


    def write_mutation_overlap(self, mutation_overlapfile, mutation_overlap, n_runs):
        tic = time.perf_counter()
        for run in range(n_runs):
            overlapfile = mutation_overlapfile + str(run) + '.txt'
            f = open(overlapfile, 'w')
            f.write('Mutation Index- Number Overlapings \n')
            for key, count in mutation_overlap[run].items():
                f.write(key + '-' + str(count) + '\n')
            f.close()

    def write_random_indiv(self, randomindiv_file, random_indiv, n_runs):
        tic = time.perf_counter()
        for run in range(n_runs):
            randomfile = randomindiv_file + str(run) + '.txt'
            f = open(randomfile, 'w')
            f.write('Individuals \n')
            for item in random_indiv[run]:
                f.write("%s\n" % item)
            f.close()

    def write_mutation_index_array(self, mutation_index_array_file, mutation_index_array):
        tic = time.perf_counter()
        f = open(mutation_index_array_file, "w")
        for item in mutation_index_array:
            f.write("%s\n" % item)
        f.close()

    def write_map_variations(self, map_variations_file, map_variations):
        tic = time.perf_counter()
        f = open(map_variations_file, 'w')
        for key, count in map_variations.items():
            f.write(key + '\t' + str(count) + '\n')
        f.close()


def handler(event):
  POP = event["array_element"]
  output_bucket = event["sifting"]["output_bucket"]
  input_bucket = event["sifting"]["input_bucket"]
  sifting_filename = event["sifting"]["output_sifting"]
  individuals_merge_filename = event["individuals_merge"]["merge_outputfile_name"]

  #download files
  siftfile = os.path.join("/tmp", "sifting.txt")
  individuals_merge_file = os.path.join("/tmp", "individuals_merge.tar.gz")
  pop_file = os.path.join("/tmp", POP)
  columns_file = os.path.join("/tmp", "columns.txt")

  client = storage.storage.get_instance()
  client.download(output_bucket, sifting_filename, siftfile)
  client.download(output_bucket, individuals_merge_filename, individuals_merge_file)
  client.download(input_bucket, POP, pop_file)
  client.download(input_bucket, "columns.txt", columns_file)

  #chromosome number, doesn't matter here - just used for naming
  c = 21


  SIFT = 'NO-SIFT'
  n_runs = 1000
  n_indiv = 52

  data_dir = '/tmp/'
  pop_dir = '/tmp/'
  outdata_dir = "/tmp/chr{0}-{1}-freq/output_no_sift/".format(str(c), str(POP)) 
  plot_dir = "/tmp/chr{0}-{1}-freq/plots_no_sift/".format(str(c), str(POP)) 

  if not os.path.exists(outdata_dir):
      os.makedirs(outdata_dir, exist_ok=True)
  if not os.path.exists(plot_dir):
      os.makedirs(plot_dir, exist_ok=True)

  OutputFormat = '.png'
  chrom = 'chr' + str(c)

  font = {'family': 'serif', 'size': 14}
  plt.rc('font', **font)

  # untar input data
  import tarfile

  tar = tarfile.open(individuals_merge_file)
  tar.extractall(path='/tmp/' + individuals_merge_filename)
  tar.close()

  rd = ReadData()
  res = Results()
  wr = WriteData()
  pd = PlotData()

  histogram_overlapfile = outdata_dir + 'Histogram_mutation_overlap_chr' + str(c) + '_s' + \
                          str(SIFT) + '_' + POP + '_'
  mutation_overlapfile = outdata_dir + 'Mutation_overlap_chr' + str(c) + '_s' + \
                          str(SIFT) + '_' + POP + '_'
  mutation_index_array_file = outdata_dir + 'mutation_index_array' + str(c) + '_s' + \
                              str(SIFT) + '_' + POP + '.txt'
  histogram_overlap_plot = plot_dir + 'Frequency_mutations' + str(c) + '_s' + \
                            str(SIFT) + '_' + POP
  map_variations_file = outdata_dir + 'map_variations' + str(c) + '_s' + \
                        str(SIFT) + '_' + POP + '.txt'

  randomindiv_file = outdata_dir + 'random_indiv' + str(c) + '_s' + \
                      str(SIFT) + '_' + POP + '_'

  ids = rd.read_names(POP, pop_dir, columns_file)
  n_pairs = len(ids) / 2

  rs_numbers, map_variations = rd.read_rs_numbers(siftfile, SIFT)
  mutation_index_array = rd.read_individuals(ids, rs_numbers, data_dir, chrom, individuals_merge_filename)

  wr.write_map_variations(map_variations_file, map_variations)
  wr.write_mutation_index_array(mutation_index_array_file, mutation_index_array)

  mutation_overlap, random_indiv = res.overlap_ind(ids, mutation_index_array, n_runs, n_indiv)
  histogram_overlap = res.histogram_overlap(mutation_overlap, n_runs)

  wr.write_mutation_overlap(mutation_overlapfile, mutation_overlap, n_runs)
  wr.write_histogram_overlap(histogram_overlapfile, histogram_overlap, n_runs, n_indiv)
  wr.write_random_indiv(randomindiv_file, random_indiv, n_runs)

  pd.plot_histogram_overlap(POP, histogram_overlap, histogram_overlap_plot, n_runs)

  # gen final output
  tar = tarfile.open('/tmp/chr%s-%s-freq.tar.gz' % (c, POP), 'w:gz')
  tar.add(outdata_dir)
  tar.add(plot_dir)
  tar.close()

  result_name = client.upload(output_bucket, 'chr%s-%s-freq.tar.gz' % (c, POP), '/tmp/chr%s-%s-freq.tar.gz' % (c, POP))

  return {
      "output_frequency": result_name
  }

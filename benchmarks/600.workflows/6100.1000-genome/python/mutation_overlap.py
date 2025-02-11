import time

tic = time.perf_counter()
import numpy as np
from random import sample
import os
import os.path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import itertools
from matplotlib import pyplot
import matplotlib as mpl
import collections
from collections import Counter
import datetime

import os
from . import storage


class ReadData :
    def read_names(self, POP, pop_dir, columns_file) :
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

    def read_rs_numbers(self, siftfile, SIFT) :
        ## NB This file is in the format of:
        ## line number, rs number, ENSG number, SIFT, Phenotype
        tic = time.perf_counter()
        rs_numbers = []
        variations = {}
        map_variations = {}
        all_variations = []
        sift_file = open(siftfile,'r')
        for item in sift_file:
            item = item.split()
            if len(item) > 2:
                rs_numbers.append(item[1])
                map_variations[item[1]] = item[2]
        
        return rs_numbers, map_variations
    
    def read_individuals(self, ids, rs_numbers, data_dir, chrom, individuals_merge_filename) :
        tic = time.perf_counter()
        mutation_index_array = []
        total_mutations={}  
        total_mutations_list =[]    
        for name in ids :
            filename = data_dir + individuals_merge_filename + '/' + chrom + '.' + name
            f = open(filename, 'r')
            text = f.read()
            f.close()
            text = text.split()
            sifted_mutations = list(set(rs_numbers).intersection(text))
            mutation_index_array.append(sifted_mutations)
            total_mutations[name]= len(sifted_mutations)
            total_mutations_list.append(len(sifted_mutations))
        
        return mutation_index_array, total_mutations, total_mutations_list    
   
    def read_pairs_overlap(self, indpairsfile) :
        tic = time.perf_counter()
        pairs_overlap = np.loadtxt(indpairsfile, unpack=True)
        pairs_overlap = np.transpose(pairs_overlap)

        return pairs_overlap


class Results :

    def group_indivuals(self, total_mutations_list, n_runs) :
        tic = time.perf_counter()
        n_group = 26
        random_mutations_list= []
        for run in range(n_runs):
            random_mutations_list.append(sample(total_mutations_list, n_group))
        return random_mutations_list

    def pair_individuals(self, mutation_index_array, n_runs) :
        tic = time.perf_counter()
    
        n_p = len(mutation_index_array)
        n_pairs = int(round(n_p/2))
        list_p = np.linspace(0, n_p - 1, n_p).astype(int)
        pairs_overlap = np.zeros((n_runs, n_pairs))
        for run in range(n_runs) :
            randomized_list = sample(list(list_p) , n_p)
            for pq in range(n_pairs) :
                array1 = mutation_index_array[randomized_list[2*pq]]
           
                array2 = mutation_index_array[randomized_list[2*pq]]
                pair_array = set(array1) & set(array2)
                pairs_overlap[run][pq] = len(pair_array)

        return pairs_overlap

    def total_pair_individuals (self, mutation_index_array) :
        tic = time.perf_counter()
        n_p = len(mutation_index_array)
        total_pairs_overlap = np.zeros((n_p, n_p))
        simetric_overlap = np.zeros((n_p, n_p))
        for run in range(n_p):
                        array1 = mutation_index_array[run]
                        start = run +1
                        for pq in range(start, n_p) :
                                array2 = mutation_index_array[pq]
                                pairs_array = set(array1) & set(array2)
                                total_pairs_overlap[run][pq]=len(pairs_array)
                                simetric_overlap[run][pq] = len(pairs_array)
                                simetric_overlap[pq][run]= len(pairs_array)

        return total_pairs_overlap , simetric_overlap

    def half_pair_individuals(self, mutation_index_array) :
        tic = time.perf_counter()
        n_p = len(mutation_index_array)
        n_pairs = int(round(n_p/2))
        pairs_overlap = np.zeros((n_pairs, n_pairs))
        for run in range(n_pairs):
            array1 = mutation_index_array[run]
            index =0
            for pq in range(n_pairs+1, n_p):
                array2 = mutation_index_array[pq]
                pairs_array = set(array1) & set(array2)
                pairs_overlap[run][index]=len(pairs_array)

        return pairs_overlap

    def gene_pairs(self, mutation_index_array) :

        tic = time.perf_counter()
        n_p = len(mutation_index_array)
        gene_pair_list = {}
        for pp in range(n_p) :  
            pairs = itertools.combinations(mutation_index_array[pp], 2)
            for pair in pairs :
                key = str(pair)
                if key not in gene_pair_list : gene_pair_list[key] = 1
                else : gene_pair_list[key] += 1

        
        return gene_pair_list

class PlotData :        

    def individual_overlap(self, POP, pairs_overlap, outputFile, c, SIFT) :
        tic = time.perf_counter()
        
        pairs_overlap = np.array(pairs_overlap)     

        min_p = np.min(pairs_overlap)
        max_p = np.max(pairs_overlap)
        nbins = int(max_p) + 1
        n_runs = len(pairs_overlap)


        nbins = int(np.max(pairs_overlap))
        bin_centres = np.linspace(0, nbins, nbins)
        bin_edges = np.linspace(-0.5, nbins + 0.5, nbins + 1)

        fig = plt.figure(frameon=False, figsize=(10, 9))
        ax = fig.add_subplot(111)
        hists = []
        max_h = 0
        for run in range(n_runs) :
            h, edges = np.histogram(pairs_overlap[run], bins = bin_edges)
            ax.plot(bin_centres, h, alpha = 0.5)
            if len(h) > 0:
                max_h = max(max_h, max(h))

        plt.xlabel('Number of overlapping gene mutations', fontsize = 24)
        plt.ylabel(r'frequency', fontsize = 28)
        text1 = 'population ' + POP + '\n' +\
            'chromosome ' + str(c) + '\n' + \
            'SIFT < ' + str(SIFT) + '\n' + \
            str(n_runs) + ' runs'
        plt.text(.95, .95, text1, fontsize = 24, 
            verticalalignment='top', horizontalalignment='right',
            transform = ax.transAxes)
        plt.savefig(outputFile)  
        plt.close()

    def total_colormap_overlap(self, POP, total_pairs_overlap, outputFile):
        tic = time.perf_counter()
        fig = plt.figure()
        cmap = mpl.colors.ListedColormap(['blue','black','red', 'green', 'pink'])
        img = pyplot.imshow(total_pairs_overlap,interpolation='nearest', cmap = cmap, origin='lower')
        pyplot.colorbar(img,cmap=cmap)

        plt.savefig(outputFile)  
        plt.close()


class WriteData :
    def write_pair_individuals(self, indpairsfile, pairs_overlap) : 
        tic = time.perf_counter()
        np.savetxt(indpairsfile, pairs_overlap, fmt = '%i')
    
    def write_gene_pairs(self, genepairsfile, gene_pair_list) :
        tic = time.perf_counter()
        f = open(genepairsfile, 'w')
        for key, count in gene_pair_list.items() :
            f.write(key + '\t' + str(count) + '\n')
        f.close()
    
    def write_total_indiv(self, total_mutations_filename, total_mutations) :
        tic = time.perf_counter()
        f = open(total_mutations_filename, 'w')
        for key, count in total_mutations.items() :
            f.write(key + '\t' + str(count) + '\n')
        f.close()
    
    def write_random_mutations_list(self, random_mutations_filename, random_mutations_list, n_runs) :
        for run in range(n_runs):
            filename= random_mutations_filename +'_run_' + str(run) + '.txt'
            f = open(filename, 'w')
            f.writelines(["%s\n" % item  for item in random_mutations_list[run]])
    
    def write_mutation_index_array(self, mutation_index_array_file, mutation_index_array):
        f=open(mutation_index_array_file,"w")
        for item in mutation_index_array:
            f.write("%s\n" % item)
        f.close()

    def write_map_variations(self, map_variations_file, map_variations) :
        tic = time.perf_counter()
        f = open(map_variations_file, 'w')
        for key, count in map_variations.items() :
            f.write(key + '\t' + str(count) + '\n')
        f.close()
    


def handler(event):
  POP = event["array_element"]
  benchmark_bucket = event["sifting"]["benchmark_bucket"]
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
  client.download(benchmark_bucket, output_bucket + '/' + sifting_filename, siftfile)
  client.download(benchmark_bucket, output_bucket + '/' + individuals_merge_filename, individuals_merge_file)
  client.download(benchmark_bucket, input_bucket + '/' + POP, pop_file)
  client.download(benchmark_bucket, input_bucket + '/' + "columns.txt", columns_file)
  #chromosome no, doesn't matter. 
  c = 21

  SIFT = 'NO-SIFT'
  n_runs = 1

  data_dir = '/tmp/'
  pop_dir = '/tmp/'
  outdata_dir = "/tmp/chr{0}-{1}/output_no_sift/".format(str(c), str(POP))
  plots_dir = "/tmp/chr{0}-{1}/plots_no_sift/".format(str(c), str(POP))

  if not os.path.exists(outdata_dir):
    os.makedirs(outdata_dir, exist_ok=True)
  if not os.path.exists(plots_dir):
    os.makedirs(plots_dir, exist_ok=True)

  OutputFormat = '.png'
  chrom = 'chr' + str(c)

  font = {'family':'serif',
      'size':14   }
  plt.rc('font', **font)


  # untar input data
  import tarfile
  tar = tarfile.open(individuals_merge_file)
  tar.extractall(path='/tmp/' + individuals_merge_filename)
  tar.close()

  tic = time.perf_counter()

  rd = ReadData()
  res = Results()
  wr = WriteData()
  pd = PlotData()
  
  half_indpairsfile = outdata_dir + 'individual_half_pairs_overlap_chr' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  total_indpairsfile = outdata_dir + 'total_individual_pairs_overlap_chr' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  genepairsfile = outdata_dir + 'gene_pairs_count_chr' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  random_indpairsfile = outdata_dir + '100_individual_overlap_chr' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'

  colormap = plots_dir + 'colormap_distribution_c' + str(c) + '_s' + \
          str(SIFT) + '_' + POP + OutputFormat
  half_overlap = plots_dir + 'half_distribution_c' + str(c) + '_s' + \
          str(SIFT) + '_' + POP + OutputFormat
  total_overlap = plots_dir + 'total_distribution_c' + str(c) + '_s' + \
          str(SIFT) + '_' + POP + OutputFormat
  random_overlap = plots_dir + '100_distribution_c' + str(c) + '_s' + \
          str(SIFT) + '_' + POP + OutputFormat
  
  total_mutations_filename = outdata_dir + 'total_mutations_individual' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  random_mutations_filename = outdata_dir + 'random_mutations_individual' + str(c) + '_s' + \
      str(SIFT) + '_' + POP 
  
  mutation_index_array_file = outdata_dir + 'mutation_index_array' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  
  map_variations_file = outdata_dir + 'map_variations' + str(c) + '_s' + \
      str(SIFT) + '_' + POP + '.txt'
  


  ids = rd.read_names(POP, pop_dir, columns_file)
  n_pairs = len(ids)/2
  

  rs_numbers, map_variations = rd.read_rs_numbers(siftfile, SIFT)
  mutation_index_array, total_mutations, total_mutations_list = rd.read_individuals(ids, rs_numbers, data_dir, chrom, individuals_merge_filename)
  wr.write_total_indiv(total_mutations_filename, total_mutations)
  wr.write_map_variations(map_variations_file, map_variations)    
  
  #cross-correlations mutations overlapping
  half_pairs_overlap = res.half_pair_individuals(mutation_index_array)
  total_pairs_overlap, simetric_overlap = res.total_pair_individuals(mutation_index_array)
  random_pairs_overlap = res.pair_individuals(mutation_index_array, n_runs)
  
  wr.write_mutation_index_array(mutation_index_array_file, mutation_index_array)
  wr.write_pair_individuals(half_indpairsfile, half_pairs_overlap)
  wr.write_pair_individuals(total_indpairsfile, total_pairs_overlap)
  wr.write_pair_individuals(random_indpairsfile, random_pairs_overlap,)
  
  pd.individual_overlap(POP, half_pairs_overlap, half_overlap, c, SIFT)
  pd.individual_overlap(POP, simetric_overlap, total_overlap, c, SIFT)
  pd.individual_overlap(POP, random_pairs_overlap, random_overlap, c, SIFT)
  pd.total_colormap_overlap(POP, total_pairs_overlap, colormap)

  #list of frecuency of mutations in 26 individuals
  random_mutations_list=res.group_indivuals(total_mutations_list, n_runs)
  wr.write_random_mutations_list(random_mutations_filename, random_mutations_list, n_runs)

  # gen overlapping
  gene_pair_list = res.gene_pairs(mutation_index_array)
  wr.write_gene_pairs(genepairsfile, gene_pair_list)

  # gen final output
  tar = tarfile.open('/tmp/chr%s-%s.tar.gz' % (c, POP), 'w:gz')
  tar.add(outdata_dir)
  tar.add(plots_dir)
  tar.close()
  result_name = client.upload(benchmark_bucket, output_bucket + '/' + 'chr%s-%s.tar.gz' % (c, POP), '/tmp/chr%s-%s.tar.gz' % (c, POP))
  result_name = result_name.replace(output_bucket + '/', '')

  return {
      "output_mutation_overlap": result_name
  }

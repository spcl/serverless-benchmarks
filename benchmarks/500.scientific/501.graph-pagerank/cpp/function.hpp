
#include <igraph.h>

#include <cfloat>

#include "utils.hpp"

igraph_real_t graph_pagerank
(int size, uint64_t seed, uint64_t &graph_generation_time_ms, uint64_t &compute_pr_time_ms)
{
  igraph_t graph;
  igraph_vector_t pagerank;
  igraph_real_t value;

  igraph_rng_seed(igraph_rng_default(), seed);
  {
    uint64_t start_time = timeSinceEpochMicrosec();
    igraph_barabasi_game(
      /* graph=    */ &graph,
      /* n=        */ size,
      /* power=    */ 1,
      /* m=        */ 10,
      /* outseq=   */ NULL,
      /* outpref=  */ 0,
      /* A=        */ 1.0,
      /* directed= */ 0,
      /* algo=     */ IGRAPH_BARABASI_PSUMTREE_MULTIPLE,
      /* start_from= */ 0
    );
    graph_generation_time_ms = (timeSinceEpochMicrosec() - start_time);
  }

  igraph_vector_init(&pagerank, 0);
  {
    uint64_t start_time = timeSinceEpochMicrosec();
    igraph_pagerank(&graph, IGRAPH_PAGERANK_ALGO_PRPACK,
                    &pagerank, &value,
                    igraph_vss_all(), IGRAPH_DIRECTED,
                    /* damping */ 0.85, /* weights */ NULL,
                    NULL /* not needed with PRPACK method */);
    compute_pr_time_ms = (timeSinceEpochMicrosec() - start_time);
  }
  /* Check that the eigenvalue is 1, as expected. */
  if (fabs(value - 1.0) > 32*DBL_EPSILON) {
      fprintf(stderr, "PageRank failed to converge.\n");
      return 1;
  }

  igraph_real_t result = VECTOR(pagerank)[0];

  igraph_vector_destroy(&pagerank);
  igraph_destroy(&graph);
  
  return result;
}


#include <aws/core/utils/json/JsonSerializer.h>
#include <igraph.h>

#include <chrono>
#include <cstdint>
#include <random>
#include <vector>

#include "utils.hpp"

Aws::Utils::Array<Aws::Utils::Json::JsonValue>
create_bfs_json(const igraph_vector_int_t &order,
                const igraph_vector_int_t &layers,
                const igraph_vector_int_t &father) {
  Aws::Utils::Array<Aws::Utils::Json::JsonValue> mainArray(3);

  // Array 1: Order (visited vertices)
  Aws::Utils::Array<Aws::Utils::Json::JsonValue> orderArray(igraph_vector_int_size(&order));
  for (int i = 0; i < igraph_vector_int_size(&order); i++) {
    orderArray[i].AsInteger((int)VECTOR(order)[i]);
  }
  mainArray[0].AsArray(std::move(orderArray));

  // Array 2: Layers (start indices)
  Aws::Utils::Array<Aws::Utils::Json::JsonValue> layersArray(igraph_vector_int_size(&layers));
  for (int i = 0; i < igraph_vector_int_size(&layers); i++) {
    layersArray[i].AsInteger((int)VECTOR(layers)[i]);
  }
  mainArray[1].AsArray(std::move(layersArray));

  // Array 3: Father (parent vertices)
  Aws::Utils::Array<Aws::Utils::Json::JsonValue> fatherArray(igraph_vector_int_size(&father));
  for (int i = 0; i < igraph_vector_int_size(&father); i++) {
    fatherArray[i].AsInteger((int)VECTOR(father)[i]);
  }
  mainArray[2].AsArray(std::move(fatherArray));

  return mainArray;
}

Aws::Utils::Json::JsonValue function(Aws::Utils::Json::JsonView request) {
  int size = request.GetInteger("size");

  uint64_t seed;
  if (request.ValueExists("seed")) {
    seed = request.GetInteger("seed");
    igraph_rng_seed(igraph_rng_default(), seed);
  } else {
    std::random_device rd;
    seed = rd();
  }
  igraph_rng_seed(igraph_rng_default(), seed);

  auto graph_gen_start = timeSinceEpochMicrosec();
  igraph_t graph;
  igraph_barabasi_game(&graph, size,
                       1,       // power
                       10,      // m
                       nullptr, // outseq
                       0,       // outpref
                       1.0,     // A
                       0,       // directed
                       IGRAPH_BARABASI_PSUMTREE,
                       0 // start_from
  );
  auto graph_gen_end = timeSinceEpochMicrosec();

  // Measure BFS time
  auto bfs_start = timeSinceEpochMicrosec();

  // Return a tuple identical to the Python API output
  // C++ API does not return the second tuple element: "The start indices of the
  // layers in the vertex list" Thus, we have to recompute it. First, we get the
  // order and parents - like in Python.
  //
  // Then, since we do not have start indices of each layer, we get the distance
  // of each vertex, and use the change point in this array to detect when a new
  // layer was created.
  igraph_vector_int_t order, father, dist, layers;

  igraph_vector_int_init(&order, 0);
  igraph_vector_int_init(&father, 0);
  igraph_vector_int_init(&dist, 0);
  igraph_vector_int_init(&layers, 0);

  // Documentation: https://igraph.org/c/pdf/0.9.7/igraph-docs.pdf
  igraph_bfs_simple(&graph, 0, IGRAPH_ALL, &order, &layers, &father);
  auto bfs_end = timeSinceEpochMicrosec();

  // Calculate times in microseconds
  auto graph_generating_time = graph_gen_end - graph_gen_start;
  auto process_time = bfs_end - bfs_start;

  Aws::Utils::Json::JsonValue result;

  result.WithArray("result", create_bfs_json(order, layers, father));

  Aws::Utils::Json::JsonValue measurement;
  measurement.WithInt64("graph_generating_time", graph_generating_time);
  measurement.WithInt64("compute_time", process_time);

  result.WithObject("measurement", std::move(measurement));

  igraph_vector_int_destroy(&order);
  igraph_vector_int_destroy(&layers);
  igraph_vector_int_destroy(&father);
  igraph_vector_int_destroy(&dist);
  igraph_destroy(&graph);

  return result;
}

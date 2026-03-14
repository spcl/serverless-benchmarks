#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>
#include <igraph.h>

#include <chrono>
#include <cstdint>
#include <random>
#include <vector>

#include "utils.hpp"

rapidjson::Value create_bfs_json(
  const igraph_vector_int_t &order,
  const igraph_vector_int_t &layers,
  const igraph_vector_int_t &father,
  rapidjson::Document::AllocatorType& alloc
) {
  rapidjson::Value mainArray(rapidjson::kArrayType);

  // Array 1: Order (visited vertices)
  rapidjson::Value orderArray(rapidjson::kArrayType);
  for (int i = 0; i < igraph_vector_int_size(&order); i++) {
    orderArray.PushBack(rapidjson::Value((int)VECTOR(order)[i]), alloc);
  }
  mainArray.PushBack(orderArray, alloc);

  // Array 2: Layers (start indices)
  rapidjson::Value layersArray(rapidjson::kArrayType);
  for (int i = 0; i < igraph_vector_int_size(&layers); i++) {
    layersArray.PushBack(rapidjson::Value((int)VECTOR(layers)[i]), alloc);
  }
  mainArray.PushBack(layersArray, alloc);

  // Array 3: Father (parent vertices)
  rapidjson::Value fatherArray(rapidjson::kArrayType);
  for (int i = 0; i < igraph_vector_int_size(&father); i++) {
    fatherArray.PushBack(rapidjson::Value((int)VECTOR(father)[i]), alloc);
  }
  mainArray.PushBack(fatherArray, alloc);

  return mainArray;
}

rapidjson::Document function(const rapidjson::Value& request) {
  int size = request["size"].GetInt();

  uint64_t seed;
  if (request.HasMember("seed")) {
    seed = (uint64_t)request["seed"].GetInt64();
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

  rapidjson::Document result;
  result.SetObject();
  auto& alloc = result.GetAllocator();

  result.AddMember("result", create_bfs_json(order, layers, father, alloc), alloc);

  rapidjson::Value measurement(rapidjson::kObjectType);
  measurement.AddMember("graph_generating_time", (int64_t)graph_generating_time, alloc);
  measurement.AddMember("compute_time", (int64_t)process_time, alloc);

  result.AddMember("measurement", measurement, alloc);

  igraph_vector_int_destroy(&order);
  igraph_vector_int_destroy(&layers);
  igraph_vector_int_destroy(&father);
  igraph_vector_int_destroy(&dist);
  igraph_destroy(&graph);

  return result;
}

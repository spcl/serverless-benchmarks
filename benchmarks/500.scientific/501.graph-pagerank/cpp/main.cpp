// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

#include <rapidjson/document.h>
#include <rapidjson/writer.h>
#include <rapidjson/stringbuffer.h>

#include "function.hpp"
#include "storage.hpp"
#include "utils.hpp"

#include <fstream>
#include <random>
#include <iostream>
#include <vector>
#include <climits>  // Required for ULLONG_MAX

rapidjson::Document function(const rapidjson::Value& request)
{
  int size = request["size"].GetInt();

  uint64_t seed;
  if (request.HasMember("seed")) {
    seed = (uint64_t)request["seed"].GetUint64();
  } else {
    double random_value = 0.0;
    seed = static_cast<uint64_t>(random_value * ULLONG_MAX);
  }

  uint64_t graph_generation_time_ms;
  uint64_t compute_pr_time_ms;
  igraph_real_t value = graph_pagerank
    (size, seed, graph_generation_time_ms, compute_pr_time_ms);

  rapidjson::Document val;
  val.SetObject();
  auto& alloc = val.GetAllocator();

  rapidjson::Value measurements(rapidjson::kObjectType);
  measurements.AddMember("graph_generating_time", (int64_t)graph_generation_time_ms, alloc);
  measurements.AddMember("compute_time", (int64_t)compute_pr_time_ms, alloc);

  val.AddMember("result", static_cast<double>(value), alloc);
  val.AddMember("measurements", measurements, alloc);

  return val;
}

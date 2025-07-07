
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>

#include "function.hpp"
#include "storage.hpp"
#include "utils.hpp"

#include <fstream>
#include <random>
#include <iostream>
#include <vector>
#include <climits>  // Required for ULLONG_MAX

Aws::Utils::Json::JsonValue function(Aws::Utils::Json::JsonView request)
{
  Storage client_ = Storage::get_client();

  auto size = request.GetInteger("size");

  uint64_t seed;
  if (request.ValueExists("seed")) {
    seed = request.GetInteger("seed");
  } else {
    double random_value = 0.0;
    seed = static_cast<uint64_t>(random_value * ULLONG_MAX);
  }

  uint64_t graph_generation_time_ms;
  uint64_t compute_pr_time_ms;
  igraph_real_t value = graph_pagerank
    (size, seed, graph_generation_time_ms, compute_pr_time_ms);

  Aws::Utils::Json::JsonValue val;
  Aws::Utils::Json::JsonValue result;
  Aws::Utils::Json::JsonValue measurements;

  measurements.WithInteger("graph_generating_time", graph_generation_time_ms);
  measurements.WithInteger("compute_time", compute_pr_time_ms);

  val.WithDouble("value", static_cast<double>(value));
  val.WithObject("measurements", std::move(measurements));
  return val;
}
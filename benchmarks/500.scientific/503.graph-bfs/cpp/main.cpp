#include <aws/core/utils/json/JsonSerializer.h>
#include <igraph.h>

#include <chrono>
#include <vector>
#include <cstdint>
#include <random>

#include "utils.hpp"

Aws::Utils::Json::JsonValue function(Aws::Utils::Json::JsonView request)
{
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
    igraph_barabasi_game(
        &graph,
        size,
        1,      // power
        10,     // m
        nullptr,// outseq
        0,      // outpref
        1.0,    // A
        0,      // directed
        IGRAPH_BARABASI_PSUMTREE_MULTIPLE,
        0       // start_from
    );
    auto graph_gen_end = timeSinceEpochMicrosec();

    // Measure BFS time
    auto bfs_start = timeSinceEpochMicrosec();
    igraph_vector_int_t order;
    igraph_vector_int_init(&order, 0);
    // Documentation: https://igraph.org/c/pdf/0.9.7/igraph-docs.pdf
    igraph_bfs(
        &graph,
        0,          // root vertex
        nullptr,    // roots
        IGRAPH_ALL, // neimode
        true,       // unreachable
        nullptr,    // restricted
        &order,     // order
        nullptr,    // rank
        nullptr,    // father
        nullptr,    // pred
        nullptr,    //succ,
        nullptr,    // dist
        nullptr,    // callback
        nullptr     // extra
    );
    auto bfs_end = timeSinceEpochMicrosec();

    // Calculate times in microseconds
    auto graph_generating_time = graph_gen_end - graph_gen_start;
    auto process_time =bfs_end - bfs_start;

    Aws::Utils::Json::JsonValue result;

    igraph_real_t bfs_result = VECTOR(order)[0];
    result.WithDouble("result", static_cast<double>(bfs_result));

    Aws::Utils::Json::JsonValue measurement;
    measurement.WithInt64("graph_generating_time", graph_generating_time);
    measurement.WithInt64("compute_time", process_time);

    result.WithObject("measurement", std::move(measurement));

    igraph_vector_int_destroy(&order);
    igraph_destroy(&graph);

    return result;
}
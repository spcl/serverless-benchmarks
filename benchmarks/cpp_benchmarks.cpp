#include <benchmark/benchmark.h>

static void BM_FunctionName(benchmark::State& state) {
  // Setup code here
  for (auto _ : state) {
    // Code to benchmark here
  }
  // Teardown code here
}

BENCHMARK(BM_FunctionName);

BENCHMARK_MAIN();


#include <benchmark/benchmark.h>

static void Setup(benchmark::State& state) {
  // Setup code here
  for (auto _ : state) {
    // Code to benchmark here
  }
  // Teardown code here
}

BENCHMARK(Setup);

BENCHMARK_MAIN();


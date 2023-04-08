#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <chrono>
#include <iomanip>

#include <benchmark/benchmark.h>

void run_cpp_benchmark() {
  std::vector<std::string> compile_cmd = {"g++", "-std=c++11", "-O3", "-DNDEBUG", "-I./benchmark/include", "cpp_benchmark.cpp", "-o", "cpp_benchmark"};
  std::vector<std::string> run_cmd = {"./cpp_benchmark", "--benchmark_format=json"};

  std::ostringstream compile_out;
  int compile_ret = benchmark::RunSpecifiedCommand(compile_cmd, &compile_out);
  if (compile_ret != 0) {
    std::cerr << "Failed to compile C++ benchmark:\n" << compile_out.str() << std::endl;
    return;
  }

  std::ostringstream run_out;
  int run_ret = benchmark::RunSpecifiedCommand(run_cmd, &run_out);
  if (run_ret != 0) {
    std::cerr << "Failed to run C++ benchmark:\n" << run_out.str() << std::endl;
    return;
  }

  std::string output = run_out.str();
  std::istringstream ss(output);
  std::string line;

  while (std::getline(ss, line)) {
    std::istringstream ls(line);
    std::string field, value;
    std::getline(ls, field, ':');
    std::getline(ls, value, ',');

    if (field == "\"name\"") {
      std::string benchmark_name = value.substr(1, value.size() - 2);
      double benchmark_time = 0.0;

      while (std::getline(ss, line) && line != "},") {
        std::istringstream ls(line);
        std::string field, value;
        std::getline(ls, field, ':');
        std::getline(ls, value, ',');

        if (field == "\"real_time\"") {
          benchmark_time = std::stod(value) / benchmark::kNumIterations;
        }
      }

      overall_results[benchmark_name]["cpp"] = benchmark_time;
    }
  }
}

// ...

int main(int argc, char** argv) {
  // ...

  // Run the C++ benchmark
  run_cpp_benchmark();

  // Print the overall results
  // ...

  return 0;
}

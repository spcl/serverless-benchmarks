cmake_minimum_required(VERSION 3.5)

project(serverless-benchmarks)

# Set up the C++ compiler options
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Add the benchmark library
add_subdirectory(benchmark)

# Add your project executable
add_executable(cpp_benchmark cpp_benchmark.cpp)

# Link your executable with the benchmark library
target_link_libraries(cpp_benchmark benchmark)

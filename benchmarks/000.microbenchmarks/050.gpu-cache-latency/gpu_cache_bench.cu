// gpu_cache_bench.cu
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <random>
#include <string>
#include <cuda_runtime.h>

__global__ void pointer_chase(int* next, int start, int iters,
                              unsigned long long* cycles_out) {
    int cur = start;
    unsigned long long t0 = clock64();
    for (int i = 0; i < iters; ++i) {
        cur = next[cur];
    }
    unsigned long long t1 = clock64();
    cycles_out[0] = t1 - t0;
}

// very bare-bones error macro
#define CHECK(call)                                                   \
    do {                                                              \
        cudaError_t e = (call);                                       \
        if (e != cudaSuccess) {                                       \
            fprintf(stderr, "CUDA error: %s\n", cudaGetErrorString(e));\
            return 1;                                                 \
        }                                                             \
    } while (0)

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr,
                "Usage: %s <working_set_bytes> <pattern> <iterations>\n",
                argv[0]);
        return 1;
    }

    size_t ws_bytes = std::stoull(argv[1]);
    std::string pattern = argv[2];     // "sequential", "stride_4", "random"
    int iters = std::stoi(argv[3]);

    size_t n = ws_bytes / sizeof(int);
    if (n == 0) n = 1;

    // host array of indices
    std::vector<int> h_next(n);

    if (pattern == "sequential") {
        for (size_t i = 0; i < n; ++i)
            h_next[i] = (i + 1) % n;
    } else if (pattern.rfind("stride_", 0) == 0) {  // starts with "stride_"
        int stride = std::stoi(pattern.substr(strlen("stride_")));
        for (size_t i = 0; i < n; ++i)
            h_next[i] = (i + stride) % n;
    } else if (pattern == "random") {
        std::vector<int> perm(n);
        for (size_t i = 0; i < n; ++i) perm[i] = i;
        std::mt19937 rng(42);
        std::shuffle(perm.begin(), perm.end(), rng);
        for (size_t i = 0; i < n; ++i)
            h_next[perm[i]] = perm[(i + 1) % n];
    } else {
        fprintf(stderr, "Unknown pattern '%s'\n", pattern.c_str());
        return 1;
    }

    int* d_next = nullptr;
    unsigned long long* d_cycles = nullptr;

    CHECK(cudaMalloc(&d_next, n * sizeof(int)));
    CHECK(cudaMalloc(&d_cycles, sizeof(unsigned long long)));
    CHECK(cudaMemcpy(d_next, h_next.data(), n * sizeof(int),
                     cudaMemcpyHostToDevice));

    dim3 grid(1), block(1);
    pointer_chase<<<grid, block>>>(d_next, 0, iters, d_cycles);
    CHECK(cudaDeviceSynchronize());

    unsigned long long cycles;
    CHECK(cudaMemcpy(&cycles, d_cycles, sizeof(unsigned long long),
                     cudaMemcpyDeviceToHost));

    cudaDeviceReset();

    // Print JSON for SeBS to parse
    // (you can extend with more fields if you want)
    printf("{\"working_set_bytes\": %zu, \"pattern\": \"%s\", "
           "\"iterations\": %d, \"total_cycles\": %llu}\n",
           ws_bytes, pattern.c_str(), iters, (unsigned long long)cycles);

    return 0;
}

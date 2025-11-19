#include <cstdio>
#include <cstdlib>
#include <vector>
#include <random>
#include <string>
#include <algorithm>
#include <cuda_runtime.h>

// Simple error macro
#define CHECK(call)                                                    \
    do {                                                               \
        cudaError_t e = (call);                                        \
        if (e != cudaSuccess) {                                        \
            fprintf(stderr, "CUDA error: %s (%d)\n",                   \
                    cudaGetErrorString(e), (int)e);                    \
            exit(1);                                                   \
        }                                                              \
    } while (0)

// Kernel: pointer chasing with an accumulator "sink" to prevent optimization
__global__ void pointer_chase(const int* next,
                              int start,
                              int iters,
                              unsigned long long* cycles_out,
                              int* sink_out) {
    int cur = start;
    int acc = 0;

    // Optional warmup
    int warmup_iters = min(iters, 1024);
    for (int i = 0; i < warmup_iters; ++i) {
        cur = next[cur];
        acc += cur;
    }

    unsigned long long t0 = clock64();
    for (int i = 0; i < iters; ++i) {
        cur = next[cur];
        acc += cur;
    }
    unsigned long long t1 = clock64();

    if (threadIdx.x == 0 && blockIdx.x == 0) {
        cycles_out[0] = t1 - t0;
        sink_out[0] = acc; // observable side effect
    }
}

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr,
                "Usage: %s <working_set_bytes> <pattern> <iterations>\n",
                argv[0]);
        return 1;
    }

    size_t ws_bytes = std::strtoull(argv[1], nullptr, 10);
    std::string pattern = argv[2];     // "sequential", "stride_4", "random"
    int iters = std::atoi(argv[3]);

    size_t n = ws_bytes / sizeof(int);
    if (n == 0) n = 1;

    // Build index array on host
    std::vector<int> h_next(n);

    if (pattern == "sequential") {
        for (size_t i = 0; i < n; ++i)
            h_next[i] = (int)((i + 1) % n);
    } else if (pattern.rfind("stride_", 0) == 0) {
        int stride = std::stoi(pattern.substr(std::string("stride_").size()));
        for (size_t i = 0; i < n; ++i)
            h_next[i] = (int)((i + stride) % n);
    } else if (pattern == "random") {
        std::vector<int> perm(n);
        for (size_t i = 0; i < n; ++i) perm[i] = (int)i;
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
    int* d_sink = nullptr;

    CHECK(cudaMalloc(&d_next, n * sizeof(int)));
    CHECK(cudaMalloc(&d_cycles, sizeof(unsigned long long)));
    CHECK(cudaMalloc(&d_sink, sizeof(int)));

    CHECK(cudaMemcpy(d_next, h_next.data(), n * sizeof(int),
                     cudaMemcpyHostToDevice));

    dim3 grid(1), block(1);
    pointer_chase<<<grid, block>>>(d_next, 0, iters, d_cycles, d_sink);
    CHECK(cudaDeviceSynchronize());

    unsigned long long cycles = 0;
    int sink_val = 0;

    CHECK(cudaMemcpy(&cycles, d_cycles, sizeof(unsigned long long),
                     cudaMemcpyDeviceToHost));
    CHECK(cudaMemcpy(&sink_val, d_sink, sizeof(int),
                     cudaMemcpyDeviceToHost));

    cudaFree(d_next);
    cudaFree(d_cycles);
    cudaFree(d_sink);
    cudaDeviceReset();

    double avg_cycles = (iters > 0) ? (double)cycles / (double)iters : 0.0;

    // Print JSON
    printf("{\"working_set_bytes\": %zu, \"pattern\": \"%s\", "
           "\"iterations\": %d, \"total_cycles\": %llu, "
           "\"avg_cycles\": %.3f, \"sink\": %d}\n",
           ws_bytes, pattern.c_str(), iters,
           (unsigned long long)cycles, avg_cycles, sink_val);

    return 0;
}

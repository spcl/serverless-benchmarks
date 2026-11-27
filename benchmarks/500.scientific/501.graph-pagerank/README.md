# 501.graph-pagerank - Graph PageRank

**Type:** Scientific
**Languages:** Python, Node.js, C++, Java
**Architecture:** x64, arm64

## Description

The benchmark represents scientific computations offloaded to serverless functions. It uses the `python-igraph` library to generate an input graph and process it with the PageRank algorithm.

For random generation of the Barabasi input graph, we use different solutions depending on the language:
* Python uses the default `random` library, which internally uses the Mersenne Twister algorithm.
* C++ uses the default PRNG of `igraph`, which is Mersenne Twister or PCG32 depending on the version of `igraph`.
* Node.js uses the `pure-rand` library since the default `Math.random()` cannot be seeded. We use the `xoroshiro128plus` generator because it is recommended by library's documentation.
* Java implements a SplitMix64 generator, the graph generator of the Node.js version and PageRank by hand, without libraries. Its PageRank agrees with igraph's on the same graph to within 1e-13.

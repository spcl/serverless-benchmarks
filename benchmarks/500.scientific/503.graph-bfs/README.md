# 503.graph-bfs - Graph BFS

**Type:** Scientific
**Languages:** Python, C++
**Architecture:** x64, arm64

## Description

The benchmark represents scientific computations offloaded to serverless functions. It uses the `python-igraph` library to generate an input graph and process it with the Breadth-First Search (BFS) algorithm.

Python 3.9 uses `python-igraph` 0.9, which reports the BFS root as its own
parent. Newer igraph versions report `-1`. Output validation canonicalizes these
equivalent root sentinels before checking the deterministic result checksum.

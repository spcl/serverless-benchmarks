
## Benchmark Applications


| Type 		   | Benchmark           | Languages          | Description          |
| :---         | :---:               | :---:              | :---:                |
| Webapps      | 110.dynamic-html    | Python, Node.js    | Generate dynamic HTML from a template. |
| Webapps      | 120.uploader    | Python, Node.js    | Uploader file from provided URL to cloud storage. |
| Multimedia      | 210.thumbnailer    | Python, Node.js    | Generate a thumbnail of an image. |
| Multimedia      | 220.video-processing    | Python    | Add a watermark and generate gif of a video file. |
| Utilities      | 311.compression    | Python   | Create a .zip file for a group of files in storage and return to user to download. |
| Utilities      | 504.dna-visualization    | Python   | Creates a visualization data for DNA sequence. |
| Inference      | 411.image-recognition    | Python    | Image recognition with ResNet and pytorch. |
| Scientific      | 501.graph-pagerank    | Python    | PageRank implementation with igraph. |
| Scientific      | 502.graph-mst    | Python    | Minimum spanning tree (MST)  implementation with igraph. |
| Scientific      | 503.graph-bfs    | Python    | Breadth-first search (BFS) implementation with igraph. |

For details on benchmark selection and their characterization, please refer to [our paper](#paper).

> **Note**
> Benchmark 411.image-recognition contains PyTorch which is often too large to fit into a code package. Up to Python 3.7, we can directly ship the dependencies. For Python 3.8 and 3.9, we used an additional zipping step that requires additional setup during the first run, making cold invocations slower. Warm invocations are not affected.

> **Note**
> Benchmarks whose number starts with the digit 0, such as `020.server-reply` are internal microbenchmarks used by specific experiments. They are not intended to be directly invoked by users.

## Workflow Applications

**(WiP)** Coming soon!


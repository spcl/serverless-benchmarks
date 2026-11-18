# Benchmark Applications

| Type 		   | Benchmark           | Languages          | Architecture       |  Description |
| :---         | :---:               | :---:              | :---:                | :---:                |
| Webapps      | 010.sleep    | Python, Node.js, C++, Java | x64, arm64 | Customizable sleep microbenchmark. |
| Webapps      | 110.dynamic-html    | Python, Node.js, Java | x64, arm64 | Generate dynamic HTML from a template. |
| Webapps      | 120.uploader    | Python, Node.js    | x64, arm64 | Uploader file from provided URL to cloud storage. |
| Webapps      | 130.crud-api    | Python, Node.js    | x64, arm64 | Simple CRUD application using NoSQL to store application data. |
| Multimedia      | 210.thumbnailer    | Python, Node.js, C++ | x64, arm64 | Generate a thumbnail of an image. |
| Multimedia      | 220.video-processing    | Python, Node.js   | x64, arm64 | Add a watermark and generate gif of a video file. |
| Utilities      | 311.compression    | Python, Node.js   | x64, arm64 | Create a .zip file for a group of files in storage and return to user to download. |
| Inference      | 411.image-recognition    | Python, C++ | x64 | Image recognition with ResNet and pytorch. |
| Scientific      | 501.graph-pagerank    | Python, Node.js, C++ | x64, arm64 | PageRank implementation with igraph. |
| Scientific      | 502.graph-mst    | Python    | x64, arm64 | Minimum spanning tree (MST)  implementation with igraph. |
| Scientific      | 503.graph-bfs    | Python, C++ | x64, arm64 | Breadth-first search (BFS) implementation with igraph. |
| Scientific      | 504.dna-visualisation    | Python   | x64, arm64 | Creates a visualization data for DNA sequence. |
| MCP tools      | 610.api-proxy    | Python   | x64, arm64 | MCP tool wrapping a REST API: waits on an upstream service, then reshapes its JSON. |
| MCP tools      | 620.fetch-markdown    | Python   | x64, arm64 | MCP fetch tool: downloads a web page and converts it to markdown. |

For more details on benchmark selection and their characterization, please refer to [our papers](../README.md#publications). Detailed information about each benchmark can be found in its respective README.md file.

> [!NOTE]
> Benchmarks whose number starts with the digit 0, such as `020.server-reply` are internal microbenchmarks used by specific experiments. They are not intended to be directly invoked by users.
> The only exception is benchmark `010.sleep`, which is a customizable sleep microbenchmark.

> [!NOTE]
> ARM architecture is available only for AWS Lambda. C++ benchmarks are currently not supported on the ARM architecture.

> [!NOTE]
> While we attempt to achieve semantically the same behavior across languages in each benchmark, there are some minor differences and there is no guarantee of binary reproducibility across languages. For example, in benchmark `411.image-recognition` we load weights and import the model structure from Python package, whereas the C++ version imports a serialized TorchScript model. Similarly, graph benchmarks will not produce exactly the same result, as Python and C++ interfaces to `igraph` library use different RNGs.

## Webapps

### 110.dynamic-html - Dynamic HTML

Generate dynamic HTML from a template. [Details →](../benchmarks/100.webapps/110.dynamic-html/README.md)

### 120.uploader - Uploader

Upload file from provided URL to cloud storage. [Details →](../benchmarks/100.webapps/120.uploader/README.md)

### 130.crud-api - CRUD API

Simple CRUD application using NoSQL to store application data. [Details →](../benchmarks/100.webapps/130.crud-api/README.md)

## Multimedia

### 210.thumbnailer - Thumbnailer

Generate a thumbnail of an image. [Details →](../benchmarks/200.multimedia/210.thumbnailer/README.md)

### 220.video-processing - Video Processing

Add a watermark and generate gif of a video file. [Details →](../benchmarks/200.multimedia/220.video-processing/README.md)

## Utilities

### 311.compression - Compression

Create a .zip file for a group of files in storage and return to user to download. [Details →](../benchmarks/300.utilities/311.compression/README.md)

## Inference

### 411.image-recognition - Image Recognition

Image recognition with ResNet and pytorch. [Details →](../benchmarks/400.inference/411.image-recognition/README.md)

## Scientific

### 501.graph-pagerank - Graph PageRank

PageRank implementation with igraph. [Details →](../benchmarks/500.scientific/501.graph-pagerank/README.md)

### 502.graph-mst - Graph MST

Minimum spanning tree (MST) implementation with igraph. [Details →](../benchmarks/500.scientific/502.graph-mst/README.md)

### 503.graph-bfs - Graph BFS

Breadth-first search (BFS) implementation with igraph. [Details →](../benchmarks/500.scientific/503.graph-bfs/README.md)

### 504.dna-visualisation - DNA Visualization

Creates a visualization data for DNA sequence. [Details →](../benchmarks/500.scientific/504.dna-visualisation/README.md)

## MCP tools

Benchmarks with an `mcp.json` file next to their language directories can also be called as a tool over the
[Model Context Protocol](https://modelcontextprotocol.io) (Streamable HTTP, stateless, JSON responses).
The same deployed function serves both: a request whose body is a JSON-RPC message (`initialize`,
`tools/list`, `tools/call`, `ping`) is answered by the MCP shim in `benchmarks/wrappers/mcp/python`, any other
request follows the usual path. On AWS, use the function URL; on the local platform, the `/mcp` route.
SeBS measurements are returned in the tool result's `_meta.sebs`. Currently supported for Python on AWS
and the local platform; `010.sleep` and `110.dynamic-html` include a tool definition.

The two benchmarks below model the most common kinds of MCP tools. Both call an upstream HTTP service
given by `SEBS_MOCK_UPSTREAM`, whose delay and response size are set per call.

### 610.api-proxy - API Proxy

MCP tool wrapping a REST API: waits on an upstream service, then reshapes its JSON. [Details →](../benchmarks/600.mcp/610.api-proxy/README.md)

### 620.fetch-markdown - Fetch Markdown

MCP fetch tool: downloads a web page and converts it to markdown. [Details →](../benchmarks/600.mcp/620.fetch-markdown/README.md)

## Serverless Workflows

**(WiP)** Coming soon!

## Applications

**(WiP)** Coming soon!

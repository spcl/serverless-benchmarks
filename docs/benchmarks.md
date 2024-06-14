
## Benchmark Applications

| Type 		   | Benchmark           | Languages          | Description          |
| :---         | :---:               | :---:              | :---:                |
| Webapps      | 110.dynamic-html    | Python, Node.js    | Generate dynamic HTML from a template. |
| Webapps      | 120.uploader    | Python, Node.js    | Uploader file from provided URL to cloud storage. |
| Multimedia      | 210.thumbnailer    | Python, Node.js    | Generate a thumbnail of an image. |
| Multimedia      | 220.video-processing    | Python    | Add a watermark and generate gif of a video file. |
| Utilities      | 311.compression    | Python   | Create a .zip file for a group of files in storage and return to user to download. |
| Inference      | 411.image-recognition    | Python    | Image recognition with ResNet and pytorch. |
| Scientific      | 501.graph-pagerank    | Python    | PageRank implementation with igraph. |
| Scientific      | 502.graph-mst    | Python    | Minimum spanning tree (MST)  implementation with igraph. |
| Scientific      | 503.graph-bfs    | Python    | Breadth-first search (BFS) implementation with igraph. |
| Scientific      | 504.dna-visualisation    | Python   | Creates a visualization data for DNA sequence. |

Below, we discuss the most important implementation details of each benchmark. For more details on benchmark selection and their characterization, please refer to [our paper](../README.md#publication).

> [!NOTE] 
> Benchmarks whose number starts with the digit 0, such as `020.server-reply` are internal microbenchmarks used by specific experiments. They are not intended to be directly invoked by users.

> [!WARNING] 
> Benchmark 411.image-recognition contains PyTorch which is often too large to fit into a code package. Up to Python 3.7, we can directly ship the dependencies. For Python 3.8, we use an additional zipping step that requires additional setup during the first run, making cold invocations slower. Warm invocations are not affected.

> [!WARNING] 
> Benchmark `411.image-recognition` does not work on AWS with Python 3.9 due to excessive code size. While it is possible to ship the benchmark by zipping `torchvision` and `numpy` (see `benchmarks/400.inference/411.image-recognition/python/package.sh`), this significantly affects cold startup. On the lowest supported memory configuration of 512 MB, the cold startup can reach 30 seconds, making HTTP trigger unusable due to 30 second timeout of API gateway. In future, we might support Docker-based deployment on AWS that are not affected by code size limitations.

> [!WARNING] 
> Benchmark `411.image-recognition` does not work on GCP with Python 3.8 and 3.9 due to excessive code size. To the best of our knowledge, there is no way of circumventing that limit, as Google Cloud offers neither layers nor custom Docker images.

## Webapps

### Dynamic HTML

The benchmark represents a dynamic generation of webpage contents through a serverless function. It generates an HTML from an existing template, with random numbers inserted to control the output. It uses the `jinja2` and `mustache` libraries on Python and Node.js, respectively.

### Uploader

The benchmark implements the common workflow of uploading user-defined data to the persistent cloud storage. It accepts a URL, downloads file contents, and uploads them to the storage. Python implementation uses the standard library `requests`, while the Node.js version uses the third-party `requests` library installed with `npm`.

## Multimedia

### Thumbnailer

This benchmark implements one of the most common functions implemented with serverless functions. It downloads an image from the cloud storage, resizes it to a thumbnail size, uploads the new smaller version to the cloud storage, and returns the location to the caller, allowing them to insert the newly created thumbnail. To resize the image, it uses the `Pillow` and `sharp` libraries on Python and Node.js, respectively.

### Video Processing

The benchmark implements two operations on video files: adding a watermark and creating a gif. Both input and output media are passed through the cloud storage. To process the video, the benchmark uses `ffmpeg`. The benchmark installs the most recent static binary of `ffmpeg` provided by [John van Sickle](https://johnvansickle.com/ffmpeg/).

## Utilities

### Compression

The benchmark implements a common functionality of websites managing file operations - gather a set of files in cloud storage, compress them together, and return a single archive to the user.
It implements the .zip file creation with the help of the `shutil` standard library in Python.

## Inference

### Image Recognition

The benchmark is inspired by MLPerf and implements image recognition with Resnet50. It downloads the input and model from the storage and uses the CPU-only `pytorch` library in Python.

## Scientific

### Graph PageRank, BFS, MST

The benchmark represents scientific computations offloaded to serverless functions. It uses the `python-igraph` library to generate an input graph and process it with the selected algorithm.

### DNA Visualization

This benchmark is inspired by the [DNAVisualization](https://github.com/Benjamin-Lee/DNAvisualization.org) project and it implements processing the `.fasta` file with the `squiggle` Python library.

## Serverless Workflows

**(WiP)** Coming soon!

## Applications

**(WiP)** Coming soon!


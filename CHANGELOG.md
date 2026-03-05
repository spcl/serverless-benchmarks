
## WiP [1.2.0](https://github.com/spcl/serverless-benchmarks/compare/v1.1...v1.2) (XXXX)

### Features

#### Container & Multi-Architecture Support

* Container deployment support for AWS Lambda (#205)
* Multi-architecture support (x86_64, arm64) for benchmarks (#227)

#### Language Support

* **C++ benchmarks**: Full support for C++ on AWS Lambda with dependency management system (#99, #251)
  - Docker-based build system with dependency caching
  - Dynamic dependency resolution with CMake generation
  - Support for Boost, OpenCV, igraph, PyTorch, hiredis libraries
  - C++ implementations: 010.sleep, 210.thumbnailer, 501.graph-pagerank, 503.graph-bfs, 411.image-recognition
* **Java benchmarks**: initial support for Java on all four platforms (#223), including benchmark **110.dynamic-html**.
* **Python**: Updated support for Python 3.8, 3.9, 3.10, 3.11, 3.12
* **Node.js**: Updated support for Node.js 14, 16, 18, 20

#### NoSQL Database Support

* Complete NoSQL storage integration across platforms (#214)
  - AWS: DynamoDB support with query interface
  - Azure: CosmosDB integration
  - GCP: Cloud Datastore support
  - Local/OpenWhisk: ScyllaDB for local testing
* New CRUD API benchmark (130.crud-api) demonstrating NoSQL operations (#214)
* Multi-tier storage system with both object and NoSQL storage

#### Platform-Specific Enhancements

* **AWS**:
  - Container deployment with ECR integration
  - Support for ARM64 Lambda functions
  - DynamoDB table management
  - Updated Lambda runtime support (#166)
* **Azure**:
  - CosmosDB database management
  - Improved HTTP trigger handling
* **GCP**:
  - Datastore database management
  - Updated dependency versions for Python 3.10+
  - Custom deployment waiters
* **Local**:
  - ScyllaDB wrapper for NoSQL database 
  - Improved container lifecycle management
  - Memory measurement improvements
* **OpenWhisk**:
  - ScyllaDB wrapper for NoSQL database 
  - Adapted to new container build API
  - Downloading metrics 

### Bug Fixes

* Fix init.sh to quote variables and add curl fallback (#287)
* Fix bug in type serialization (#264)
* Add SeBS user agent to 120.uploader (#255)
* Fix GCP and local deployment issues (#252)
* Fix local deployment invocation issues (#231, #249)
* Fix invocation overhead experiment (#240)
* Fix storage connection timeout on non-Linux platforms (#197)
* Fix PyTorch benchmark support for Python 3.8 and 3.9 (#165)
* Fix memory measurements on local deployment (#136)
* Fix incorrect igraph version (#113)
* Fix cache handling for code packages and containers

### Improvements

* Comprehensive docstrings across codebase (#244)
* Sphinx-based HTML documentation with API reference (#244)
* Update linting process (#241)
* Dynamic port mapping for function containers in local deployment (#199)
* Single-bucket design for cloud storage (#186)
* Improved handling of cloud credentials (#181)
* Invocation statistics reporting for benchmark and experiment results
* Improved logging throughout the system
* Improved storage and benchmarks documentation
* Versioning for Docker build images
* Support for multiple Azure subscriptions
* Enhanced regression test system with container and ARM support

### Deprecations

* Python 3.6 no longer supported on all platforms
* Node.js 8, 10, 12 deprecated on various platforms
* Older runtime versions phased out across AWS, Azure, and GCP.

### Contributors

This release includes contributions from:
* @userlaurin - multi-platform robustness (#287)
* @DJAntivenom - C++ benchmark bugfixes (#264)
* @HoriaMercan - C++benchmarks (#251)
* @rabbull - GCP bug fixes (#252), local deployment fixes (#249)
* @qdelamea-aneo - Fix invocation overhead experiment (#240)
* @ojninja16 - Versioning and resource IDs (#232)
* @MahadMuhammad - Fixes in local deployment (#231)
* @aidenh6307 - Local documentation updates (#210)
* @prajinkhadka - Container support for AWS (#205)
* @octonawish-akcodes - Local deployment and benchmark version improvements (#198)
* @Kaleab-git - Dynamic port mapping (#199), storage timeout fix (#197)
* @nurSaadat - Documentation improvements (#175)
* @lawrence910426 - Colored CLI output (#141)
* @alevy - Documentation improvements (#139)
* @skehrli - Local memory measurements (#101)
* @mahlashrifi - Java benchmarks support (#223)
* @xSurus - improvements and extensions to Java benchmarks (#223)
* And many others who contributed bug reports, testing, and feedback!

## [1.1.0](https://github.com/spcl/serverless-benchmarks/compare/v1.0...v1.1) (2022-05-30)

### Features

* Support for the open-source FaaS platform OpenWhisk.
* New system of handling non-root containers that do not require rebuilding Docker images.
* Initial release of deploying functions as Docker containers, first released on OpenWhisk.
* Support for function states on AWS for correct deployment and configuration updates.

### Improvements

* Deprecate Python 3.6 on all platforms.
* Update documentation and tutorials.
* Docker build images for AWS now use official AWS images.
* AWS Lambda functions now support Python 3.9 and Node.js 14. Python 3.6 and Node.js 8 are no longer supported.
* Azure Functions support now Python 3.8 and Python 3.9, and Node.js 12 and 14. Python 3.6, Node.js 8, and 10 are no longer supported.
* Google Cloud Functions support now Node 12 and 14. Node 6 and 8 are no longer supported.
* OpenWhisk supports Python 3.7 and 3.9, Node.js 10 and 12.

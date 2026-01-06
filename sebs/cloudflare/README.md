# Cloudflare Workers Implementation for SeBS

This directory contains the **complete implementation** of Cloudflare Workers support for the SeBS (Serverless Benchmarking Suite).

## Implementation Status

✅ **Fully Implemented** - All features are production-ready:
- Multi-language support (JavaScript, Python, Java, Go, Rust) via containers
- Per-invocation metrics via response measurements (no external dependencies)
- Storage integration (R2 for object storage, Durable Objects for NoSQL)
- Script and container-based deployments
- HTTP and Library trigger support

## Key Components

### 1. `cloudflare.py` - Main System Implementation

This file implements the core Cloudflare Workers platform integration, including:

- **`create_function()`** - Creates a new Cloudflare Worker
  - Checks if worker already exists
  - Uploads worker script or container image via Cloudflare API
  - Configures Durable Objects bindings for containerized workers
  - Adds HTTP and Library triggers
  - Returns a `CloudflareWorker` instance

- **`cached_function()`** - Handles cached functions
  - Refreshes triggers and logging handlers for functions retrieved from cache

- **`update_function()`** - Updates an existing worker
  - Uploads new script content
  - Updates worker configuration

- **`update_function_configuration()`** - Updates worker configuration
  - Note: Cloudflare Workers have limited runtime configuration compared to AWS Lambda or Azure Functions
  - Memory and CPU time limits are managed by Cloudflare

- **`package_code()`** - Prepares code for deployment
  - Packages code for both script-based and container-based worker deployments
  - Supports JavaScript/Node.js scripts and multi-language containers
  - Returns package path and size

### 2. `function.py` - CloudflareWorker Class

Represents a Cloudflare Worker function with:
- Worker name and script/container ID
- Runtime information (script or container-based)
- Serialization/deserialization for caching
- Account ID association
- Trigger configurations (HTTP and Library)

### 3. `config.py` - Configuration Classes

Contains three main classes:

- **`CloudflareCredentials`** - Authentication credentials
  - Supports API token or email + API key
  - Requires account ID
  - Can be loaded from environment variables or config file

- **`CloudflareResources`** - Platform resources
  - R2 storage bucket configuration
  - Durable Objects for NoSQL operations
  - Resource ID management

- **`CloudflareConfig`** - Overall configuration
  - Combines credentials and resources
  - Handles serialization to/from cache

### 4. `triggers.py` - Trigger Implementations

- **`LibraryTrigger`** - Programmatic invocation via Cloudflare API
- **`HTTPTrigger`** - HTTP invocation via worker URLs
  - Workers are automatically accessible at `https://{name}.{account}.workers.dev`

This provides the behavior of SeBS to invoke serverless functions via either library or http triggers.

### 5. `resources.py` - System Resources

Handles Cloudflare-specific resources including:
- **R2 Buckets** - Object storage (S3-compatible) for benchmark data
- **Durable Objects** - Stateful storage for NoSQL operations

This defines SeBS behavior to upload benchmarking resources and cleanup before/after benchmarks. It is different from the benchmark wrapper, which provides the functions for benchmarks to perform storage operations during execution.

## Usage
### Environment Variables

Set the following environment variables:

```bash
# Option 1: Using API Token (recommended)
export CLOUDFLARE_API_TOKEN="your-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"

# Option 2: Using Email + API Key
export CLOUDFLARE_EMAIL="your-email@example.com"
export CLOUDFLARE_API_KEY="your-global-api-key"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
```

### Configuration File

Alternatively, create a configuration file:

```json
{
  "cloudflare": {
    "credentials": {
      "api_token": "your-api-token",
      "account_id": "your-account-id"
    },
    "resources": {
      "resources_id": "unique-resource-id"
    }
  }
}
```

### Implemented Features

- **Container Deployment**: ✅ Fully implemented
  - Container-based workers using @cloudflare/containers
  - Multi-language support via containerization
  - Script and container-based deployment supported
- **Per-Invocation Metrics**: ✅ Implemented via response measurements
  - Per-request performance data collected in worker response
  - CPU time and wall time tracking
  - Metrics extracted immediately from ExecutionResult objects
- **Language Support**: ✅ Multi-language support
  - JavaScript/Node.js via script deployment
  - Python, Java, Go, Rust, and more via container deployment
- **Storage Resources**: ✅ Fully integrated
  - Cloudflare R2 for main storage (S3-compatible object storage)
  - Cloudflare Durable Objects for NoSQL storage
  - Integrated with benchmark wrappers

### Platform Limitations

- **Cold Start Enforcement**: Not available (Workers are instantiated on-demand at edge locations)
- **Memory/Timeout Configuration**: Managed by Cloudflare (128MB memory, 50ms CPU time on free tier)

### Completed Enhancements

#### High Priority ✅
- [x] **Container Deployment Support**
  - Multi-language support (Python, Java, Go, Rust, etc.) via @cloudflare/containers
  - Wrangler CLI integration for deployment
  - Durable Objects binding for container orchestration
  - See [implementation details](#container-support-architecture) below
- [x] **Storage Resources**
  - Main storage: Cloudflare R2 (S3-compatible) integration complete
  - NoSQL storage: Cloudflare Durable Objects support implemented
  - Benchmark wrappers updated for storage operations
- [x] **Metrics Collection**
  - Response-based per-invocation metrics
  - Immediate availability (no external service dependency)
  - CPU time, wall time, and billing calculations

#### Standard Priority ✅
- [x] Wrangler CLI integration for deployment and bundling
- [x] Support for Cloudflare R2 (object storage)
- [x] Support for Durable Objects (NoSQL/stateful storage)
- [x] Container-based multi-language workers

## Metrics Collection

### Overview

Cloudflare Workers metrics are collected **directly from the worker response** during each invocation. This provides immediate, accurate per-invocation performance data without requiring external analytics services or API queries.

### Why Response-Based Metrics?

| Feature | Response Measurements | External Analytics |
|---------|---------------------|--------------------|
| **Data Granularity** | ✅ Per-invocation | ❌ Aggregated |
| **Request ID Matching** | ✅ Direct correlation | ❌ Impossible to correlate |
| **Latency** | ✅ Immediate | ❌ Delayed (30-60s) |
| **SeBS Compatibility** | ✅ Perfect match | ❌ Additional complexity |
| **Cost** | ✅ Free | ❌ May require paid plan |
| **Plan Requirement** | ✅ Any plan | ❌ May require paid plan |

### How It Works

1. **Worker Execution**: During each invocation, the worker handler measures performance:
   - Captures start time using `time.perf_counter()`
   - Executes the benchmark function
   - Measures elapsed time in microseconds
   - Collects request metadata (request ID, timestamps)

2. **Response Structure**: Worker returns JSON with embedded metrics:
   ```json
   {
     "begin": 1704556800.123,
     "end": 1704556800.456,
     "compute_time": 333000,
     "request_id": "cf-ray-abc123",
     "result": {...},
     "is_cold": false
   }
   ```

3. **Metrics Extraction**: SeBS `download_metrics()` method:
   - Iterates through `ExecutionResult` objects
   - Extracts metrics from response measurements
   - Populates `provider_times.execution` (CPU time in μs)
   - Sets `stats.cold_start` based on response data
   - Calculates `billing.billed_time` and `billing.gb_seconds`

### Handler Integration

Benchmark wrappers automatically include metrics in their responses. The Python handler (in `benchmarks/wrappers/cloudflare/python/handler.py`) demonstrates the pattern:

```python
# Start timing
start = time.perf_counter()
begin = datetime.datetime.now().timestamp()

# Execute benchmark
ret = handler(event, context)

# Calculate timing
end = datetime.datetime.now().timestamp()
elapsed = time.perf_counter() - start
micro = elapsed * 1_000_000  # Convert to microseconds

# Return response with embedded metrics
return Response(json.dumps({
    'begin': begin,
    'end': end,
    'compute_time': micro,
    'result': ret,
    'is_cold': False,
    'request_id': req_id
}))
```

### Response Schema

Worker responses include these fields for metrics collection:

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `begin` | Float | Start timestamp | `1704556800.123` |
| `end` | Float | End timestamp | `1704556800.456` |
| `compute_time` | Float | CPU time (μs) | `333000.0` |
| `request_id` | String | Request identifier | `"cf-ray-abc123"` |
| `is_cold` | Boolean | Cold start flag | `false` |
| `result` | Object | Benchmark output | `{...}` |

### Metrics Extraction Process

When `download_metrics()` is called in `cloudflare.py`, SeBS:

1. **Iterates ExecutionResults**: Loops through all tracked invocations
2. **Extracts Response Data**: Reads metrics from the response JSON already captured
3. **Populates Provider Times**: Sets `provider_times.execution` from `compute_time`
4. **Calculates Billing**: Computes GB-seconds using Cloudflare's fixed 128MB memory
5. **Aggregates Statistics**: Creates summary metrics (avg/min/max CPU time, cold starts)

Example from `cloudflare.py`:

```python
for request_id, result in requests.items():
    # Count cold/warm starts
    if result.stats.cold_start:
        cold_starts += 1
    
    # Extract CPU time from response measurement
    if result.provider_times.execution > 0:
        cpu_times.append(result.provider_times.execution)
    
    # Calculate billing
    cpu_time_seconds = result.provider_times.execution / 1_000_000.0
    gb_seconds = (128.0 / 1024.0) * cpu_time_seconds
    result.billing.gb_seconds = int(gb_seconds * 1_000_000)
```

### Implementation Notes

1. **Immediate Availability**: Metrics are available immediately in the response (no delay)
2. **Wrapper Consistency**: All benchmark wrappers follow the same response schema
3. **Billing Calculations**: Based on Cloudflare's fixed 128MB memory allocation and CPU time
4. **Cold Start Detection**: Currently always reports `false` (Cloudflare doesn't expose cold start info)

### Troubleshooting

**Missing Metrics in Results**:
- Verify worker handler returns complete JSON response with all required fields
- Check that `compute_time`, `begin`, `end` fields are present in response
- Ensure wrapper code hasn't been modified to remove metric collection
- Confirm response JSON is properly formatted

**Incorrect Timing Values**:
- Verify `time.perf_counter()` is being used for microsecond precision
- Check that timing starts before benchmark execution and ends after
- Ensure no external fetch requests are inflating the measured time
- Confirm microsecond conversion (multiply seconds by 1,000,000)

**Container Deployment Issues**:
- Ensure Docker is installed and running locally
- Verify wrangler CLI is installed (`npm install -g wrangler`)
- Check that @cloudflare/containers package is in dependencies
- Confirm Durable Objects bindings are correctly configured in wrangler.toml
- Ensure container image size is under Cloudflare's limits

**Worker Deployment Failures**:
- Verify Cloudflare credentials are correctly configured
- Check account has Workers enabled (may require paid plan for some features)
- Ensure worker name doesn't conflict with existing workers
- Review wrangler logs for specific error messages

### References

- [Cloudflare Workers Runtime APIs](https://developers.cloudflare.com/workers/runtime-apis/)
- [Workers Bindings](https://developers.cloudflare.com/workers/configuration/bindings/)
- [Durable Objects Documentation](https://developers.cloudflare.com/durable-objects/)
- [R2 Storage Documentation](https://developers.cloudflare.com/r2/)

---

## Container Support Architecture

### Overview

Cloudflare container support for Workers is integrated into SeBS using the `@cloudflare/containers` package, enabling deployment of containerized applications across multiple programming languages.

### Implementation Details

1. **Container Orchestration**
   - Uses `@cloudflare/containers` npm package
   - Requires Node.js worker.js wrapper for orchestration
   - Container runs inside Durable Object for isolation
   - Integrated with wrangler CLI for deployment

2. **Deployment Process**
   - `package_code()` generates wrangler.toml with container configuration
   - Creates `[[migrations]]` entries for Durable Objects
   - Binds container to `CONTAINER_WORKER` Durable Object class
   - Uses `wrangler deploy` to upload both worker and container

3. **Supported Languages**
   - Python via Docker containers
   - Node.js (both script and container)
   - Go, Rust, Java (via container deployment)
   - Any language that can run in a Linux container

4. **Key Methods**
   - `_generate_wrangler_toml()`: Creates config with container bindings
   - `create_function()`: Deploys workers using wrangler CLI
   - `update_function()`: Updates existing containerized workers

### Benefits

- **Multi-language Support**: Deploy Python, Java, Go, Rust workers
- **Complex Dependencies**: Support system libraries and compiled extensions
- **Larger Code Packages**: Overcome script size limitations
- **Consistent Environments**: Same container locally and in production


## References

- [Cloudflare Workers Documentation](https://developers.cloudflare.com/workers/)
- [Cloudflare API Documentation](https://api.cloudflare.com/)
- [Workers API Reference](https://developers.cloudflare.com/workers/runtime-apis/)

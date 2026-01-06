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
- **Cold Start Detection**: ⚠️ **Not Supported** - Cloudflare does not expose cold start information
  - All invocations report `is_cold: false` (see hardcoded value in handler at line 146 of `benchmarks/wrappers/cloudflare/python/handler.py`)
  - The `measurement.is_cold` field will always be `false` regardless of actual worker state
  - **Impact on benchmarks**: Cold start metrics are incomparable to AWS Lambda, Azure Functions, or GCP Cloud Functions
  - **Warning**: This limitation may skew benchmark comparisons when analyzing cold start performance across platforms
  - Workers are instantiated on-demand at edge locations with minimal latency, but this state is not observable
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

# Execute benchmark function
from function import function
ret = function.handler(event)

# Build response with nested measurement data
log_data = {
    'output': ret['result']
}
if 'measurement' in ret:
    log_data['measurement'] = ret['measurement']
else:
    log_data['measurement'] = {}

# Add memory usage to measurement
if HAS_RESOURCE:
    memory_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    log_data['measurement']['memory_used_mb'] = memory_mb

# Calculate timing
end = datetime.datetime.now().timestamp()
elapsed = time.perf_counter() - start
micro = elapsed * 1_000_000  # Convert to microseconds

# Return response with top-level wrapper fields and nested measurement
return Response(json.dumps({
    'begin': begin,
    'end': end,
    'compute_time': micro,  # Not used by SeBS
    'results_time': 0,       # Not used by SeBS
    'result': log_data,      # Contains nested measurement
    'is_cold': False,        # Not used by SeBS (uses measurement.is_cold)
    'is_cold_worker': False, # Not used by SeBS
    'container_id': "0",     # Not used by SeBS
    'environ_container_id': "no_id",  # Not used by SeBS
    'request_id': req_id
}))
```

### Response Schema

Worker responses include these fields:

#### Top-Level Fields (Wrapper Metadata)

| Field | Type | Used by SeBS? | Purpose |
|-------|------|---------------|----------|
| `begin` | Float | ❌ No | Start timestamp (legacy) |
| `end` | Float | ❌ No | End timestamp (legacy) |
| `compute_time` | Float | ❌ No | Wrapper overhead time (not benchmark time) |
| `results_time` | Float | ❌ No | Reserved for future use |
| `is_cold` | Boolean | ❌ No | Legacy field (use `measurement.is_cold`) |
| `is_cold_worker` | Boolean | ❌ No | Not used |
| `container_id` | String | ❌ No | Container identifier (informational) |
| `environ_container_id` | String | ❌ No | Environment container ID (informational) |
| `request_id` | String | ✅ Yes | Request identifier for tracking |
| `result` | Object | ✅ Yes | Contains `output` and `measurement` |

#### Nested Measurement Fields (result.measurement)

These are the **actual fields consumed by SeBS** from `result['result']['measurement']`:

| Field | Type | Used by SeBS? | Purpose | Populated By |
|-------|------|---------------|---------|-------------|
| `cpu_time_us` | Integer | ✅ Yes | CPU time in microseconds | Benchmark function |
| `cpu_time_ms` | Float | ✅ Yes | CPU time in milliseconds (fallback) | Benchmark function |
| `wall_time_us` | Integer | ✅ Yes | Wall time in microseconds | Benchmark function |
| `wall_time_ms` | Float | ✅ Yes | Wall time in milliseconds (fallback) | Benchmark function |
| `is_cold` | Boolean | ✅ Yes | True cold start indicator | Benchmark function |
| `memory_used_mb` | Float | ✅ Yes | Memory usage in megabytes | Wrapper (via resource.getrusage) |

**Example Response Structure:**

```json
{
  "begin": 1704556800.123,
  "end": 1704556800.456,
  "compute_time": 333000,
  "results_time": 0,
  "result": {
    "output": { /* benchmark output */ },
    "measurement": {
      "cpu_time_us": 150000,
      "wall_time_us": 155000,
      "is_cold": false,
      "memory_used_mb": 45.2
    }
  },
  "is_cold": false,
  "is_cold_worker": false,
  "container_id": "0",
  "environ_container_id": "no_id",
  "request_id": "cf-ray-abc123"
}
```

### Metrics Extraction Process

Metrics extraction happens in two stages:

#### Stage 1: HTTPTrigger.sync_invoke (Per-Invocation)

In `sebs/cloudflare/triggers.py`, the `HTTPTrigger.sync_invoke()` method extracts metrics from **nested measurement data** immediately after each invocation:

```python
def sync_invoke(self, payload: dict) -> ExecutionResult:
    result = self._http_invoke(payload, self.url)
    
    # Extract measurement data from result.output['result']['measurement']
    if result.output and 'result' in result.output:
        result_data = result.output['result']
        if isinstance(result_data, dict) and 'measurement' in result_data:
            measurement = result_data['measurement']
            
            if isinstance(measurement, dict):
                # CPU time in microseconds (with ms fallback)
                if 'cpu_time_us' in measurement:
                    result.provider_times.execution = measurement['cpu_time_us']
                elif 'cpu_time_ms' in measurement:
                    result.provider_times.execution = int(measurement['cpu_time_ms'] * 1000)
                
                # Wall time in microseconds (with ms fallback)
                if 'wall_time_us' in measurement:
                    result.times.benchmark = measurement['wall_time_us']
                elif 'wall_time_ms' in measurement:
                    result.times.benchmark = int(measurement['wall_time_ms'] * 1000)
                
                # Cold start flag
                if 'is_cold' in measurement:
                    result.stats.cold_start = measurement['is_cold']
                
                # Memory usage
                if 'memory_used_mb' in measurement:
                    result.stats.memory_used = measurement['memory_used_mb']
    
    return result
```

**Note:** The top-level `compute_time` field is **ignored** by SeBS. Only the nested `measurement` object is used.

#### Stage 2: download_metrics (Aggregation)

When `download_metrics()` is called in `cloudflare.py`, SeBS aggregates the already-extracted metrics:

```python
for request_id, result in requests.items():
    # Count cold/warm starts (from measurement.is_cold)
    if result.stats.cold_start:
        cold_starts += 1
    
    # Collect CPU times (from measurement.cpu_time_us/ms)
    if result.provider_times.execution > 0:
        cpu_times.append(result.provider_times.execution)
    
    # Collect memory usage (from measurement.memory_used_mb)
    if result.stats.memory_used is not None and result.stats.memory_used > 0:
        memory_values.append(result.stats.memory_used)
    
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

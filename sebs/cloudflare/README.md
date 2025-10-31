# Cloudflare Workers Implementation for SeBS

This directory contains the implementation of Cloudflare Workers support for the SeBS (Serverless Benchmarking Suite).

## Key Components

### 1. `cloudflare.py` - Main System Implementation

This file implements the core Cloudflare Workers platform integration, including:

- **`create_function()`** - Creates a new Cloudflare Worker
  - Checks if worker already exists
  - Uploads worker script via Cloudflare API
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
  - Packages JavaScript/Node.js code for worker deployment
  - Returns package path and size

### 2. `function.py` - CloudflareWorker Class

Represents a Cloudflare Worker function with:
- Worker name and script ID
- Runtime information
- Serialization/deserialization for caching
- Account ID association

### 3. `config.py` - Configuration Classes

Contains three main classes:

- **`CloudflareCredentials`** - Authentication credentials
  - Supports API token or email + API key
  - Requires account ID
  - Can be loaded from environment variables or config file

- **`CloudflareResources`** - Platform resources
  - KV namespace IDs
  - Storage bucket mappings
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

Handles Cloudflare-specific resources like KV namespaces and R2 storage. This defines the behavior of SeBS to upload benchmarking resources and cleanup before/after the benchmark. It is different from the benchmark wrapper, which provides the functions for the benchmark itself to perform storage operations.

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

### Current Limitations

- **Container Deployment**: Not currently implemented
  - *Note*: Cloudflare recently added container support (October 2024)
  - Current implementation only supports script-based deployment
  - Container support would require:
    - Creating `CloudflareContainer` class (similar to AWS ECR)
    - Container registry integration
    - Dockerfile templates for each language
    - Updates to `package_code()` and `create_function()` methods
- **Cold Start Enforcement**: Not available (Workers are instantiated on-demand at edge locations)
- **Per-Invocation Metrics**: Limited (Cloudflare provides aggregated analytics)
- **Language Support**: Currently JavaScript/Node.js (Python support via Pyodide is experimental)
  - Container support would enable any containerized language
- **Memory/Timeout Configuration**: Fixed by Cloudflare (128MB memory, 50ms CPU time on free tier)

### Future Enhancements

#### High Priority
- [ ] **Container Deployment Support**
  - Cloudflare now supports container-based Workers (as of October 2024)
  - Would enable multi-language support (Python, Java, Go, Rust, etc.)
  - Requires implementing `CloudflareContainer` class
  - Need Cloudflare container registry integration
  - See [implementation notes](#container-support-architecture) below
- [ ] **Add Storage Resources**
  - SeBS needs two levels of storage resources, main storage and nosql storage.
  - For main storage Cloudflare R2 comes to mind.
  - For nosql storage either D1 or Durable Objects come to mind. They need to be used by the benchmark wrapper aswell. I think it needs to be consistent...

## Metrics Collection with Analytics Engine

### Overview

Cloudflare Workers metrics are collected using **Analytics Engine**, which provides **per-invocation performance data** similar to AWS CloudWatch Logs or Azure Application Insights. Unlike the GraphQL Analytics API (which only provides aggregated metrics), Analytics Engine allows workers to write custom data points during execution that can be queried later.

### Why Analytics Engine?

| Feature | Analytics Engine | GraphQL Analytics API |
|---------|-----------------|----------------------|
| **Data Granularity** | ✅ Per-invocation | ❌ Aggregated only |
| **Request ID Matching** | ✅ Direct correlation | ❌ Not possible |
| **Cold Start Detection** | ✅ Per-request | ❌ Average only |
| **SeBS Compatibility** | ✅ Full support | ❌ Limited |
| **Cost** | Free (10M writes/month) | Free |
| **Plan Requirement** | Paid plan ($5/month) | Any plan |

### How It Works

1. **Worker Execution**: During each invocation, the worker writes a data point to Analytics Engine with:
   - Request ID (for correlation with SeBS)
   - CPU time and wall time
   - Cold/warm start indicator
   - Success/error status

2. **Metrics Query**: After benchmark execution, SeBS queries Analytics Engine using SQL:
   - Retrieves all data points for the time period
   - Matches request IDs to `ExecutionResult` objects
   - Populates provider metrics (CPU time, cold starts, etc.)

3. **Data Enrichment**: Each `ExecutionResult` is enriched with:
   - `provider_times.execution` - CPU time in microseconds
   - `stats.cold_start` - True/False for cold start
   - `billing.billed_time` - Billable CPU time
   - `billing.gb_seconds` - GB-seconds for cost calculation

### Implementation Requirements

#### 1. Analytics Engine Binding

```python
# In cloudflare.py - automatically configured
self._bind_analytics_engine(worker_name, account_id)
```

#### 2. Benchmark Wrapper

Benchmark wrappers must write data points during execution. The wrapper code looks like:

```javascript
export default {
  async fetch(request, env, ctx) {
    const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
    const startTime = Date.now();
    const startCpu = performance.now();
    
    try {
      // Execute benchmark
      const result = await benchmarkHandler(request, env, ctx);
      
      // Write metrics to Analytics Engine
      if (env.ANALYTICS) {
        env.ANALYTICS.writeDataPoint({
          indexes: [requestId, result.is_cold ? 'cold' : 'warm'],
          doubles: [Date.now() - startTime, performance.now() - startCpu, 0, 0],
          blobs: [request.url, 'success', '', '']
        });
      }
      
      return new Response(JSON.stringify({...result, request_id: requestId}));
    } catch (error) {
      // Write error metrics
      if (env.ANALYTICS) {
        env.ANALYTICS.writeDataPoint({
          indexes: [requestId, 'error'],
          doubles: [Date.now() - startTime, performance.now() - startCpu, 0, 0],
          blobs: [request.url, 'error', error.message, '']
        });
      }
      throw error;
    }
  }
};
```

#### 3. Data Schema

Analytics Engine data points use this schema:

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `index1` | String | Request ID | `"req-abc-123"` |
| `index2` | String | Cold/Warm | `"cold"` or `"warm"` |
| `double1` | Float | Wall time (ms) | `45.2` |
| `double2` | Float | CPU time (ms) | `12.8` |
| `blob1` | String | Request URL | `"https://worker.dev"` |
| `blob2` | String | Status | `"success"` or `"error"` |
| `blob3` | String | Error message | `""` or error text |

### Query Process

When `download_metrics()` is called, SeBS:

1. **Builds SQL Query**: Creates a ClickHouse SQL query for the time range
2. **Executes Query**: POSTs to Analytics Engine SQL API
3. **Parses Results**: Parses newline-delimited JSON response
4. **Matches Request IDs**: Correlates data points with tracked invocations
5. **Populates Metrics**: Enriches `ExecutionResult` objects with provider data

Example SQL query:

```sql
SELECT 
  index1 as request_id,
  index2 as cold_warm,
  double1 as wall_time_ms,
  double2 as cpu_time_ms,
  blob2 as status,
  timestamp
FROM ANALYTICS_DATASET
WHERE timestamp >= toDateTime('2025-10-27 10:00:00')
  AND timestamp <= toDateTime('2025-10-27 11:00:00')
  AND blob1 LIKE '%worker-name%'
ORDER BY timestamp ASC
```

### Limitation

1. **Delay**: Typically 30-60 seconds for data to appear in Analytics Engine
2. **Wrapper Updates**: All benchmark wrappers must be updated to write data points

### Troubleshooting

**Missing Metrics**:
- Check that worker has Analytics Engine binding configured
- Verify wrapper is writing data points (check `env.ANALYTICS`)
- Wait 60+ seconds after invocation for ingestion
- Check SQL query matches worker URL pattern

**Unmatched Request IDs**:
- Ensure wrapper returns `request_id` in response
- Verify SeBS is tracking request IDs correctly
- Check timestamp range covers all invocations

**Query Failures**:
- Verify account has Analytics Engine enabled (Paid plan)
- Check API token has analytics read permissions
- Validate SQL syntax (ClickHouse format)

### References

- [Analytics Engine Documentation](https://developers.cloudflare.com/analytics/analytics-engine/)
- [Analytics Engine SQL API](https://developers.cloudflare.com/analytics/analytics-engine/sql-api/)
- [Workers Bindings](https://developers.cloudflare.com/workers/configuration/bindings/)
- See `ANALYTICS_ENGINE_IMPLEMENTATION.md` for complete implementation details 

#### Standard Priority
- [ ] Support for Cloudflare Workers KV (key-value storage)
- [ ] Support for Cloudflare R2 (object storage)
- [ ] Support for Durable Objects
- [ ] Wrangler CLI integration for better bundling
- [ ] WebAssembly/Rust worker support

---

## Container Support Architecture

### Overview

Cloudflare recently introduced container support for Workers, enabling deployment of containerized applications. Adding this to SeBS would require the following components:

### Required Components

1. **Container Client** (`container.py`)
   - Extends `sebs.faas.container.DockerContainer`
   - Manages container image builds and registry operations
   - Similar to `sebs/aws/container.py` for ECR

2. **Registry Integration**
   - Cloudflare Container Registry authentication
   - Image push/pull operations
   - Support for external registries (Docker Hub, etc.)

3. **Dockerfile Templates**
   - Create `/dockerfiles/cloudflare/{language}/Dockerfile.function`
   - Support for Node.js, Python, and other languages

4. **Updated Methods**
   - `package_code()`: Add container build path alongside script packaging
   - `create_function()`: Handle both script and container deployments
   - `update_function()`: Support updating container-based workers

### Benefits

- **Multi-language Support**: Deploy Python, Java, Go, Rust workers
- **Complex Dependencies**: Support system libraries and compiled extensions
- **Larger Code Packages**: Overcome script size limitations
- **Consistent Environments**: Same container locally and in production


## References

- [Cloudflare Workers Documentation](https://developers.cloudflare.com/workers/)
- [Cloudflare API Documentation](https://api.cloudflare.com/)
- [Workers API Reference](https://developers.cloudflare.com/workers/runtime-apis/)

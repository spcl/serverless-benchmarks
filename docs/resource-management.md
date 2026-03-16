# Resource Management

SeBS allocates cloud resources automatically on first use and reuses them across subsequent runs.
This document explains how resources are identified, named, and cleaned up.

## Resource ID

Every SeBS deployment is assigned a **`resources_id`** — a short, unique identifier that acts as a namespace for all cloud resources belonging to that deployment.
It is stored in the `Resources` base class (`sebs/faas/config.py`) and persisted in the local cache so that subsequent runs reuse the same resources rather than allocating new ones. The ID is generated in one of two ways:

- **Without a user prefix**: an 8-character UUID fragment, e.g. `a1b2c3d4`
- **With a user prefix**: `{prefix}-{8-char UUID}`, e.g. `myexp-a1b2c3d4`

The prefix is optional and can be supplied via the platform configuration.
When a prefix is provided, SeBS first scans existing cloud resources for a deployment whose ID contains that prefix and reuses it if found.
A new ID is only generated when no match exists.

After a deployment's resources are created, their identifiers are written to the local cache:
This means a typical repeated benchmark run performs no cloud resource allocation at all.

## Resource Naming

Every cloud object created by SeBS embeds the `resources_id` in its name.
This guarantees isolation between concurrent deployments (different users, CI runs, or experiments) and makes it straightforward to identify which resources belong to which deployment.

### Storage Buckets

Bucket names follow the pattern `sebs-{type}-{resources_id}`, where `type` is one of three predefined bucket roles:

| Type | Bucket name | Purpose |
|---|---|---|
| `deployment` | `sebs-deployment-{resources_id}` | Function deployment packages (ZIP files, containers) |
| `benchmarks` | `sebs-benchmarks-{resources_id}` | Benchmark input data |
| `experiments` | `sebs-experiments-{resources_id}` | Experiment results and output data |

### Serverless Functions

Each platform uses the same logical structure but applies platform-specific formatting rules. The general pattern is:

```
sebs-{resources_id}-{benchmark}-{language}-{language-version}-{architecture}[-docker]
```

For container-based AWS Lambda deployments the suffix `-docker` is appended to the function name.
Cloud platforms might apply additional character substitutions (`.` → `-`, `_` → `-`) to comply with their naming rules.

### AWS-Specific Resources

The AWS ECR repository used for container images is named `sebs-benchmarks-{resources_id}`, matching the benchmarks bucket pattern.


## Cleanup

Because every resource name embeds `resources_id`, SeBS can reliably enumerate and delete all resources associated with a deployment:
* Serverless functions
* Storage buckets and their contents
* NoSQL tables
* Platform-specific ancillary resources (HTTP APIs, CloudWatch log groups, ECR repositories, CosmosDB accounts, etc.)

After cleanup, the corresponding cache entries are removed so that a subsequent run starts fresh.

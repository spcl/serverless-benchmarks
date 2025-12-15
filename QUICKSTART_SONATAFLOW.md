# SonataFlow quickstart

This backend generates Serverless Workflow definitions from SeBS workflow specs and drives them through a running SonataFlow (Kogito) instance. Functions still run as local SeBS containers; SonataFlow orchestrates them via HTTP.

## Prerequisites
- Docker available locally.
- A SonataFlow dev-mode/runtime reachable at `http://localhost:8080` (default). Example:
  ```bash
  docker run --rm -it -p 8080:8080 \
    -v "$PWD/output/workflow_resources/sonataflow":/home/kogito/serverless-workflow-project/src/main/resources/workflows \
    quay.io/kiegroup/kogito-swf-devmode:latest
  ```
  The volume mount should point to the directory where SeBS writes generated `.sw.json` files.
  If you also need to provide `application.properties`, mount a directory to
  `/home/kogito/serverless-workflow-project/src/main/resources` that contains both
  `application.properties` and a `workflows/` subdirectory.
- Local object/NoSQL/redis services (reuse `run_local_workflows.sh` setup or `./sebs.py storage start all config/storage.json`).

## Configure
Add a `deployment.sonataflow` block to your config (based on `config/example.json`):
```json
{
  "deployment": {
    "name": "sonataflow",
    "sonataflow": {
      "resources": {
        "redis": { "host": "localhost:6380", "password": "" },
        "runtime": { "url": "http://localhost:8080", "endpoint_prefix": "" }
      },
      "storage": {
        "type": "minio",
        "address": "localhost",
        "mapped_port": 9000,
        "access_key": "minio",
        "secret_key": "minio123",
        "instance_id": "minio",
        "input_buckets": [],
        "output_buckets": []
      }
    }
  }
}
```
Adjust storage/redis endpoints to match your local services.

## Run
1. Start storage/redis (as in `run_local_workflows.sh`).
2. Start SonataFlow dev-mode and mount the output directory (see above).
3. Execute a workflow benchmark:
   ```bash
   ./sebs.py benchmark workflow 610.gen test \
     --config config/your-sonataflow-config.json \
     --deployment sonataflow --trigger http --repetitions 1 --verbose
   ```

On first run SeBS will:
- Package workflow functions into local containers.
- Translate `definition.json` into `workflow_resources/sonataflow/<workflow_id>.sw.json` under the generated code package directory (inside your `--output-dir` tree).
- Invoke SonataFlow at `{runtime_url}/{workflow_id}` with the workflow payload (and auto-fallback to `/services/{workflow_id}` if needed).

If SonataFlow dev-mode fails with a “Duplicated item found with id …” error, ensure there is only one `.sw.json` file per workflow id under the mounted resources directory.

# Storage Configuration

SeBS benchmarks rely on persistent storage for both input and output data.
Most applications use object storage for storing inputs and outputs, while others can use NoSQL database.
On cloud platforms, you can use cloud-native storage services like S3, DynamoDB, CosmosDB, or Firestore.
SeBS will automatically allocate resources and configure them.
With open-source platforms like OpenWhisk or local deployment, SeBS needs a self-hosted storage instance.

In this document, we explain how to deploy and configure storage systems for benchmarking with SeBS.
For object storage, we support two S3-compatible systems: [Minio](https://github.com/minio/minio) and [RustFS](https://github.com/rustfs/rustfs).
For NoSQL storage, we use [ScyllaDB](https://github.com/scylladb/scylladb) with an adapter that provides a DynamoDB-compatible interface.
The storage instance is deployed as a Docker container and can be retained across multiple experiments.
While we provide a default configuration that automatically deploys each storage instance,
you can deploy them on any cloud resource and adapt the configuration to fit your needs.

## Object Storage Backends

Benchmark functions access object storage through the S3 API, so both backends are interchangeable and no benchmark code changes when switching between them.
Select the backend with the `type` field of the object storage configuration; the default configuration files are `configs/storage.json` for Minio and `configs/storage-rustfs.json` for RustFS.

* **Minio** is the established default. Its community edition is no longer maintained and its images were removed from Docker Hub; SeBS pulls the pinned version from `quay.io/minio/minio`.
* **RustFS** is an actively developed, Apache-2.0 licensed alternative. Its data is kept in a named Docker volume, since the container runs as a fixed unprivileged user. At the time of writing, RustFS has not published a stable release yet, so we pin a release candidate.

## Starting Storage Services

You can start the necessary storage services using the `storage` command in SeBS:

```bash
# Start only object storage
sebs storage start object configs/storage.json --output-json storage_object.json

# Start only NoSQL database
sebs storage start nosql configs/storage.json --output-json storage_nosql.json

# Start both storage types
sebs storage start all configs/storage.json --output-json storage.json
```

The command deploys the requested storage services as Docker containers and generates a configuration file in JSON format.
This file contains all the necessary information to connect to the storage services, including endpoint addresses, credentials, and instance IDs:

```json
{
  "object": {
    "type": "minio",
    "minio": {
      "address": "172.17.0.2:9000",
      "external_address": "10.10.1.15:9011",
      "mapped_port": 9011,
      "access_key": "XXX",
      "secret_key": "XXX",
      "instance_id": "XXX",
      "output_buckets": [],
      "input_buckets": [],
      "version": "RELEASE.2024-07-16T23-46-41Z",
      "data_volume": "minio-volume",
      "type": "minio"
    }
  },
  "nosql": {
    "type": "scylladb",
    "scylladb": {
      "address": "172.17.0.3:8000",
      "external_address": "10.10.1.15:9012",
      "mapped_port": 9012,
      "alternator_port": 8000,
      "access_key": "None",
      "secret_key": "None",
      "instance_id": "XXX",
      "region": "None",
      "cpus": 1,
      "memory": "750",
      "version": "6.0",
      "data_volume": "scylladb-volume"
    }
  }
}
```

Each storage instance has two addresses:

* `address` is used by SeBS itself, e.g., to upload benchmark inputs. On Linux, this is the container's address on the default Docker bridge network (`172.17.0.2`) and the container's port (`9000`). Functions of the local deployment run on the same bridge network and use this address as well.
* `external_address` is advertised to benchmark functions that run outside of the Docker bridge network, e.g., in a Kubernetes cluster hosting OpenWhisk. It combines the IP address of the machine with the port mapped on the host: Minio is mapped to port 9011, and ScyllaDB to port 9012.

The external address is detected automatically as the IP address of the host's default network interface, and SeBS verifies that the storage answers on it. To use a different interface or a hostname, pass the `--external-address` flag when starting the storage:

```bash
sebs storage start all configs/storage.json --output-json storage.json --external-address 10.10.1.15
```

> [!WARNING]
> The mapped ports are bound on all interfaces of the host. On a machine with a public IP address, restrict access to these ports with a firewall or use a private address.

## Network Configuration

To use the deployed storage with a benchmark, pass the generated configuration file with the `--storage-configuration` flag.
The storage configuration is merged into the deployment section of the SeBS configuration, so no manual editing of JSON files is needed:

```bash
sebs benchmark invoke 210.thumbnailer test --config configs/openwhisk.json --storage-configuration storage.json
```

Functions running in OpenWhisk or another Kubernetes-based platform cannot reach the Docker bridge network of the host, even when the cluster runs on the same machine.
They connect to the storage through the external address, which is detected when starting the storage.
If the detected address is not reachable from the functions, e.g., because the machine has multiple network interfaces or the storage runs on a different host, override it without changing any files:

```bash
sebs benchmark invoke 210.thumbnailer test --config configs/openwhisk.json --storage-configuration storage.json --storage-address 10.10.1.15
```

The override applies to all storage instances, each with its own mapped port. Alternatively, provide the address once when starting the storage with `--external-address`.

You can validate that the storage is reachable with an HTTP request to Minio's health endpoint and ScyllaDB's root endpoint:

```bash
$ curl -i 10.10.1.15:9011/minio/health/live
HTTP/1.1 200 OK
...
Server: MinIO

$ curl -i 10.10.1.15:9012
HTTP/1.1 200 OK
...
healthy: 10.10.1.15:9012
```

## Lifecycle Management

By default, storage containers are retained after experiments complete. This allows you to run multiple experiments without redeploying and repopulating storage.

When you're done with your experiments, you can stop the storage services:

```bash
sebs storage stop object storage.json

sebs storage stop nosql storage.json

sebs storage stop all storage.json
```

### Erasing Volumes

Each storage service uses a Docker volume to persist data. The name of the volume is included in the storage configuration file under the `data_volume` field.

In Minio, the volume is mapped to a physical location on the filesystem, and the directory can be removed once the experiments are finished.
For RustFS and ScyllaDB, we use named Docker volumes that can be removed using Docker commands: `docker volume rm rustfs-volume scylladb-volume`.

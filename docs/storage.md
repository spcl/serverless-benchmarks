# Storage Configuration

SeBS benchmarks rely on persistent storage for both input and output data.
Most applications use object storage for storing inputs and outputs, while others can use NoSQL database.
On cloud platforms, you can use cloud-native storage services like S3, DynamoDB, CosmosDB, or Firestore.
SeBS will automatically allocate resources and configure them.
With open-source platforms like OpenWhisk or local deployment, SeBS needs a self-hosted storage instance.

In this document, we explain how to deploy and configure storage systems for benchmarking with SeBS.
For object storage, we support two S3-compatible systems: [RustFS](https://github.com/rustfs/rustfs), the default, and [Minio](https://github.com/minio/minio), which is deprecated and kept for reproducibility of earlier results.
For NoSQL storage, we use [ScyllaDB](https://github.com/scylladb/scylladb) with an adapter that provides a DynamoDB-compatible interface.
The storage instance is deployed as a Docker container and can be retained across multiple experiments.
While we provide a default configuration that automatically deploys each storage instance,
you can deploy them on any cloud resource and adapt the configuration to fit your needs.

## Object Storage Backends

Benchmark functions access object storage through the S3 API, so both backends are interchangeable and no benchmark code changes when switching between them.
Select the backend with the `type` field of the object storage configuration; the default configuration files are `configs/storage.json` for RustFS and `configs/storage-minio.json` for Minio.

Up to SeBS 1.2, Minio was the only object storage.
In September 2026, we changed the default to RustFS:

* The Minio community edition is no longer maintained, and Minio stopped publishing its server images: they were removed from Docker Hub, and `quay.io/minio/minio` no longer serves them without authentication. A fresh SeBS installation could no longer start the storage.
* RustFS is an actively developed, Apache-2.0 licensed, S3-compatible object storage with published container images. We pin an exact release (`1.0.0`) in `configs/storage.json` to keep results reproducible.

**RustFS** keeps its data in a named Docker volume, since the container runs as a fixed unprivileged user.

**Minio** is deprecated and kept only to reproduce results obtained with earlier SeBS versions.
SeBS pulls the last release it used, `RELEASE.2024-07-16T23-46-41Z`, from our archive of the image: `spcleth/serverless-benchmarks:minio-reproducibility-archive-RELEASE.2024-07-16T23-46-41Z`.
To use it, start the storage with `configs/storage-minio.json`.

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
    "type": "rustfs",
    "rustfs": {
      "address": "172.17.0.2:9000",
      "external_address": "10.10.1.15:9011",
      "mapped_port": 9011,
      "access_key": "XXX",
      "secret_key": "XXX",
      "instance_id": "XXX",
      "output_buckets": [],
      "input_buckets": [],
      "version": "1.0.0",
      "data_volume": "rustfs-volume",
      "type": "rustfs"
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
* `external_address` is advertised to benchmark functions that run outside of the Docker bridge network, e.g., in a Kubernetes cluster hosting OpenWhisk. It combines the IP address of the machine with the port mapped on the host: the object storage is mapped to port 9011, and ScyllaDB to port 9012.

The external address is detected automatically as the IP address of the host's default network interface, and SeBS verifies that the storage answers on it. To use a different interface or a hostname, pass the `--external-address` flag when starting the storage:

```bash
sebs storage start all configs/storage.json --output-json storage.json --external-address 10.10.1.15
```

The mapped ports must be reachable from wherever the functions run.
When the storage runs on a cloud VM and the functions run elsewhere, e.g., in a Kubernetes cluster, open the mapped ports (9011 and 9012 by default) in the VM's firewall and the cloud network security rules (security groups, firewall rules) for the address range of the cluster.

> [!WARNING]
> The mapped ports are bound on all interfaces of the host. On a machine with a public IP address, allow access to these ports only from the addresses of your functions, or use a private address.

## Network Configuration

To use the deployed storage with a benchmark or an experiment, pass the generated configuration file with the `--storage-configuration` flag.
The storage configuration is merged into the deployment section of the SeBS configuration, so no manual editing of JSON files is needed:

```bash
sebs benchmark invoke 210.thumbnailer test --config configs/openwhisk.json --storage-configuration storage.json
sebs experiment invoke perf-cost --config configs/openwhisk.json --storage-configuration storage.json
```

Functions running in OpenWhisk or another Kubernetes-based platform cannot reach the Docker bridge network of the host, even when the cluster runs on the same machine.
They connect to the storage through the external address, which is detected when starting the storage.
If the detected address is not reachable from the functions, e.g., because the machine has multiple network interfaces or the storage runs on a different host, provide the address when starting the storage with `--external-address`, or edit the `external_address` fields in the generated configuration file.

You can validate that the storage is reachable with an HTTP request to the health endpoint of the object storage (`/health` for RustFS, `/minio/health/live` for Minio) and ScyllaDB's root endpoint:

```bash
$ curl -i 10.10.1.15:9011/health
HTTP/1.1 200 OK
...

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

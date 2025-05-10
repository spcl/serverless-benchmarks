# Storage Configuration

SeBS benchmarks rely on persistent storage for both input and output data.
Most applications use object storage for storing inputs and outputs, while others can use NoSQL database.
On cloud platforms, you can use cloud-native storage services like S3, DynamoDB, CosmosDB, or Firestore.
SeBS will automatically allocate resources and configure them.
With open-source platforms like OpenWhisk or local deployment, SeBS needs a self-hosted storage instance.

In this document, we explain how to deploy and configure storage systems for benchmarking with SeBS.
We use [Minio](https://github.com/minio/minio), a high-performance and S3-compatible object storage, and [ScyllaDB](https://github.com/scylladb/scylladb)
with an adapter that provides a DynamoDB-compatible interface.
The storage instance is deployed as a Docker container and can be retained across multiple experiments.
While we provide a default configuration that automatically deploys each storage instance,
you can deploy them on any cloud resource and adapt the configuration to fit your needs.

## Starting Storage Services

You can start the necessary storage services using the `storage` command in SeBS:

```bash
# Start only object storage
./sebs.py storage start object config/storage.json --output-json storage_object.json

# Start only NoSQL database
./sebs.py storage start nosql config/storage.json --output-json storage_nosql.json

# Start both storage types
./sebs.py storage start all config/storage.json --output-json storage.json
```

The command deploys the requested storage services as Docker containers and generates a configuration file in JSON format.
This file contains all the necessary information to connect to the storage services, including endpoint addresses, credentials, and instance IDs:

```json
{
  "object": {
    "type": "minio",
    "minio": {
      "address": "172.17.0.2:9000",
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

As we can see, the Minio container is running on the default Docker bridge network with address `172.17.0.2` and uses port `9000`.
The default configuration maps the container's port to the host, making the storage instance available directly without referring to the container's IP address. Minio is mapped to port 9011, and ScyllaDB is mapped to port 9012.

## Network Configuration

The storage instance must be accessible from the host network, and in some cases, from external networks.
For example, the storage can be deployed on a separate virtual machine or container.
Furthermore, even on a local machine, it's necessary to configure the network address, as OpenWhisk functions
are running isolated from the host network and won't be able to reach other containers running on the Docker bridge.

When using Minio with cloud-hosted FaaS platforms like OpenWhisk or for local deployment, you need to ensure that the functions can reach the storage instance. 
By default, the container runs on the Docker bridge network with an address (e.g., `172.17.0.2`) that is not accessible from outside the host.
Even when deploying both OpenWhisk and storage on the same system, the local bridge network is not accessible from the Kubernetes cluster. 
To make it accessible, functions need to use the public IP address of the machine hosting the container instance and the mapped port.
You can typically find an externally accessible address via `ip addr`, and then replace the storage's address with the external address of the machine and the mapped port. 

For example, for an external address `10.10.1.15` (a LAN-local address on CloudLab) and mapped port `9011`, set the SeBS configuration as follows:

```bash
# For a LAN-local address (e.g., on CloudLab)
jq --slurpfile file1 storage.json '.deployment.openwhisk.storage = $file1[0] | .deployment.openwhisk.storage.address = "10.10.1.15:9011"' config/example.json > config/openwhisk.json
```

You can validate the configuration of Minio with an HTTP request by using `curl`:

```bash
$ curl -i 10.10.1.15:9011/minio/health/live
HTTP/1.1 200 OK
Accept-Ranges: bytes
Content-Length: 0
Content-Security-Policy: block-all-mixed-content
Server: MinIO
Strict-Transport-Security: max-age=31536000; includeSubDomains
Vary: Origin
X-Amz-Request-Id: 16F3D9B9FDFFA340
X-Content-Type-Options: nosniff
X-Xss-Protection: 1; mode=block
Date: Mon, 30 May 2022 10:01:21 GMT
```


## Lifecycle Management

By default, storage containers are retained after experiments complete. This allows you to run multiple experiments without redeploying and repopulating storage.

When you're done with your experiments, you can stop the storage services:

```bash
./sebs.py storage stop object storage.json

./sebs.py storage stop nosql storage.json

./sebs.py storage stop all storage.json
```

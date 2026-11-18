// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package org.serverlessbench;

import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Request;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Response;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.S3Object;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;

/**
 * Object storage, the counterpart of the Python wrapper's {@code storage} class.
 *
 * <p>Added to the deployment package only for benchmarks declaring the {@code storage} module,
 * because the SDK dominates the package size and the cold start.
 */
public final class Storage {

    private static Storage instance = null;

    private final S3Client client;

    private Storage() {
        // The URL-connection client keeps the jar small; the default client pulls in Netty.
        this.client = S3Client.builder().httpClient(UrlConnectionHttpClient.create()).build();
    }

    /**
     * Returns the shared instance, creating it on first use.
     *
     * <p>Created lazily, like the Python wrapper, so that the SDK's start-up cost falls into the
     * first invocation rather than the platform's initialization phase.
     *
     * @return the storage instance for this container
     */
    public static synchronized Storage getInstance() {
        if (instance == null) {
            instance = new Storage();
        }
        return instance;
    }

    /**
     * Inserts a random suffix before the file extension, as the other wrappers do.
     *
     * @param name key or file name to make unique
     * @return the name with a random suffix, e.g. {@code archive.1a2b3c4d.zip}
     */
    public static String uniqueName(String name) {
        int separator = name.lastIndexOf('/');
        int dot = name.lastIndexOf('.');
        String base = name;
        String extension = "";
        if (dot > separator) {
            base = name.substring(0, dot);
            extension = name.substring(dot);
        }
        String random = UUID.randomUUID().toString().split("-")[0];
        return base + "." + random + extension;
    }

    /**
     * Uploads a local file under a randomized key.
     *
     * @param bucket bucket to upload to
     * @param file key to derive the randomized key from
     * @param filepath local file to upload
     * @return the key the object was stored under
     */
    public String upload(String bucket, String file, String filepath) {
        String keyName = uniqueName(file);
        this.client.putObject(
                PutObjectRequest.builder().bucket(bucket).key(keyName).build(),
                RequestBody.fromFile(Paths.get(filepath)));
        return keyName;
    }

    /**
     * Downloads an object to a local file, creating parent directories as needed.
     *
     * @param bucket bucket to download from
     * @param file key of the object
     * @param filepath local destination path
     * @throws IOException when the destination cannot be prepared
     */
    public void download(String bucket, String file, String filepath) throws IOException {
        Path destination = Paths.get(filepath);
        Path parent = destination.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        // The SDK refuses to overwrite an existing file.
        Files.deleteIfExists(destination);
        this.client.getObject(
                GetObjectRequest.builder().bucket(bucket).key(file).build(), destination);
    }

    /**
     * Downloads every object with the given prefix, recreating the key structure under a path.
     *
     * @param bucket bucket to download from
     * @param prefix key prefix selecting the objects
     * @param path local directory to download into
     * @throws IOException when a destination cannot be prepared
     */
    public void downloadDirectory(String bucket, String prefix, String path) throws IOException {
        ListObjectsV2Request.Builder request =
                ListObjectsV2Request.builder().bucket(bucket).prefix(prefix);
        String continuationToken = null;
        boolean found = false;
        do {
            ListObjectsV2Response objects =
                    this.client.listObjectsV2(request.continuationToken(continuationToken).build());
            for (S3Object object : objects.contents()) {
                found = true;
                download(bucket, object.key(), Paths.get(path, object.key()).toString());
            }
            continuationToken = objects.nextContinuationToken();
        } while (continuationToken != null);

        if (!found) {
            throw new IOException(
                    String.format(
                            "No objects found in bucket '%s' with prefix '%s'", bucket, prefix));
        }
    }

    /**
     * Uploads in-memory data under a randomized key.
     *
     * @param bucket bucket to upload to
     * @param file key to derive the randomized key from
     * @param data bytes to upload
     * @return the key the object was stored under
     */
    public String uploadStream(String bucket, String file, byte[] data) {
        String keyName = uniqueName(file);
        this.client.putObject(
                PutObjectRequest.builder().bucket(bucket).key(keyName).build(),
                RequestBody.fromBytes(data));
        return keyName;
    }

    /**
     * Downloads an object into memory.
     *
     * @param bucket bucket to download from
     * @param file key of the object
     * @return the object's bytes
     */
    public byte[] downloadStream(String bucket, String file) {
        ResponseBytes<GetObjectResponse> response =
                this.client.getObjectAsBytes(
                        GetObjectRequest.builder().bucket(bucket).key(file).build());
        return response.asByteArray();
    }
}

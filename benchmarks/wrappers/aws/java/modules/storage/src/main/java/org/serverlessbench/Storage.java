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

/** S3 storage with the interface of the Python wrapper's {@code storage} class. */
public final class Storage {

    private static Storage instance = null;

    private final S3Client client;

    private Storage() {
        // Smaller than the SDK's default HTTP clients, which systems.json excludes
        this.client = S3Client.builder().httpClient(UrlConnectionHttpClient.create()).build();
    }

    /** Returns the shared instance, created on first use. */
    public static synchronized Storage getInstance() {
        if (instance == null) {
            instance = new Storage();
        }
        return instance;
    }

    /** Inserts a random suffix before the extension, e.g. {@code archive.1a2b3c4d.zip}. */
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

    /** Uploads a local file under {@code uniqueName(file)} and returns that key. */
    public String upload(String bucket, String file, String filepath) {
        String keyName = uniqueName(file);
        this.client.putObject(
                PutObjectRequest.builder().bucket(bucket).key(keyName).build(),
                RequestBody.fromFile(Paths.get(filepath)));
        return keyName;
    }

    /** Downloads an object to a local file, creating its parent directories. */
    public void download(String bucket, String file, String filepath) throws IOException {
        Path destination = Paths.get(filepath);
        Path parent = destination.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        // The SDK refuses to overwrite an existing file
        Files.deleteIfExists(destination);
        this.client.getObject(
                GetObjectRequest.builder().bucket(bucket).key(file).build(), destination);
    }

    /** Downloads every object under a prefix into {@code path}, keeping the key structure. */
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

    /** Uploads bytes under {@code uniqueName(file)} and returns that key. */
    public String uploadStream(String bucket, String file, byte[] data) {
        String keyName = uniqueName(file);
        this.client.putObject(
                PutObjectRequest.builder().bucket(bucket).key(keyName).build(),
                RequestBody.fromBytes(data));
        return keyName;
    }

    /** Downloads an object into memory. */
    public byte[] downloadStream(String bucket, String file) {
        ResponseBytes<GetObjectResponse> response =
                this.client.getObjectAsBytes(
                        GetObjectRequest.builder().bucket(bucket).key(file).build());
        return response.asByteArray();
    }
}

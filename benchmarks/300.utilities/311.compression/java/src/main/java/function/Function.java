// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package function;

import org.serverlessbench.Storage;

import java.io.IOException;
import java.io.OutputStream;
import java.io.UncheckedIOException;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class Function {

    @SuppressWarnings("unchecked")
    public Map<String, Object> handler(Map<String, Object> event) {
        Map<String, Object> bucketConfig = (Map<String, Object>) event.get("bucket");
        Map<String, Object> objectConfig = (Map<String, Object>) event.get("object");
        String bucket = (String) bucketConfig.get("bucket");
        String inputPrefix = (String) bucketConfig.get("input");
        String outputPrefix = (String) bucketConfig.get("output");
        String key = (String) objectConfig.get("key");

        Storage client = Storage.getInstance();
        try {
            Path downloadPath = Paths.get("/tmp", String.format("%s-%s", key, UUID.randomUUID()));
            Files.createDirectories(downloadPath);

            long downloadBegin = System.nanoTime();
            client.downloadDirectory(bucket, joinKey(inputPrefix, key), downloadPath.toString());
            long downloadEnd = System.nanoTime();
            long size = parseDirectory(downloadPath);

            String archiveName = key + ".zip";
            Path archivePath = downloadPath.resolve(archiveName);

            long compressBegin = System.nanoTime();
            compressDirectory(downloadPath, archivePath);
            long compressEnd = System.nanoTime();

            long archiveSize = Files.size(archivePath);

            long uploadBegin = System.nanoTime();
            String keyName =
                    client.upload(
                            bucket, joinKey(outputPrefix, archiveName), archivePath.toString());
            long uploadEnd = System.nanoTime();

            Map<String, Object> result = new HashMap<>();
            result.put("bucket", bucket);
            result.put("key", keyName);

            Map<String, Object> measurement = new HashMap<>();
            measurement.put("download_time", microseconds(downloadBegin, downloadEnd));
            measurement.put("download_size", size);
            measurement.put("upload_time", microseconds(uploadBegin, uploadEnd));
            measurement.put("upload_size", archiveSize);
            measurement.put("compute_time", microseconds(compressBegin, compressEnd));

            Map<String, Object> response = new HashMap<>();
            response.put("result", result);
            response.put("measurement", measurement);
            return response;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** Joins an object storage prefix and a name, as the other implementations do. */
    private static String joinKey(String prefix, String name) {
        if (prefix == null || prefix.isEmpty()) {
            return name;
        }
        return prefix + "/" + name;
    }

    private static long microseconds(long beginNanos, long endNanos) {
        return (endNanos - beginNanos) / 1000;
    }

    /** Returns the total size of every file below a directory. */
    private static long parseDirectory(Path directory) throws IOException {
        long size = 0;
        for (Path file : listFiles(directory)) {
            size += Files.size(file);
        }
        return size;
    }

    /**
     * Writes every file below a directory into a zip archive, with paths relative to it.
     *
     * <p>The archive is skipped while it is being written, so that the output of the benchmark
     * holds only the downloaded data, as in the Python and Node.js implementations.
     */
    private static void compressDirectory(Path directory, Path archive) throws IOException {
        List<Path> files = listFiles(directory);
        try (OutputStream out = Files.newOutputStream(archive);
                ZipOutputStream zip = new ZipOutputStream(out)) {
            for (Path file : files) {
                if (file.equals(archive)) {
                    continue;
                }
                String name = directory.relativize(file).toString().replace('\\', '/');
                zip.putNextEntry(new ZipEntry(name));
                Files.copy(file, zip);
                zip.closeEntry();
            }
        }
    }

    /** Collects every regular file below a directory. */
    private static List<Path> listFiles(Path directory) throws IOException {
        List<Path> files = new ArrayList<>();
        Files.walkFileTree(
                directory,
                new SimpleFileVisitor<Path>() {
                    @Override
                    public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                        if (attrs.isRegularFile()) {
                            files.add(file);
                        }
                        return FileVisitResult.CONTINUE;
                    }
                });
        return files;
    }
}

package org.serverlessbench;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

final class ColdStartTracker {

    private static final AtomicBoolean COLD = new AtomicBoolean(true);
    private static final Path MARKER = Path.of("/tmp/cold_run");
    private static String containerId = null;

    private ColdStartTracker() {}

    static boolean isCold() {
        if (Files.exists(MARKER)) {
            COLD.set(false);
            return false;
        }
        boolean first = COLD.getAndSet(false);
        if (first) {
            try {
                containerId = UUID.randomUUID().toString().substring(0, 8);
                Files.writeString(MARKER, containerId, StandardCharsets.UTF_8);
            } catch (IOException ignored) {
                // best-effort marker write
            }
        }
        return first;
    }

    static String getContainerId() {
        if (containerId == null) {
            try {
                if (Files.exists(MARKER)) {
                    containerId = Files.readString(MARKER, StandardCharsets.UTF_8);
                } else {
                    containerId = UUID.randomUUID().toString().substring(0, 8);
                    Files.writeString(MARKER, containerId, StandardCharsets.UTF_8);
                }
            } catch (IOException e) {
                containerId = UUID.randomUUID().toString().substring(0, 8);
            }
        }
        return containerId;
    }
}

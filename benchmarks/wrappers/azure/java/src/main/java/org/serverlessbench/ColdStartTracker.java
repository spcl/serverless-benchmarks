package org.serverlessbench;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

final class ColdStartTracker {

    private static final AtomicBoolean WORKER_COLD = new AtomicBoolean(true);
    private static final Path MARKER = Path.of("/tmp/cold_run");

    private ColdStartTracker() {}

    static boolean isCold() {
        if (Files.exists(MARKER)) {
            return false;
        }
        try {
            Files.writeString(
                    MARKER, UUID.randomUUID().toString().substring(0, 8), StandardCharsets.UTF_8);
        } catch (IOException ignored) {
            // best-effort marker write
        }
        return true;
    }

    static boolean isWorkerCold() {
        return WORKER_COLD.getAndSet(false);
    }
}

# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package org.serverlessbench;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

final class ColdStartTracker {

    private static final Path MARKER = Paths.get("/tmp/cold_run");
    private static String containerId = null;

    private ColdStartTracker() {}

    static boolean isCold() {
        if (Files.exists(MARKER)) {
            return false;
        }
        try {
            containerId = UUID.randomUUID().toString().substring(0, 8);
            Files.write(MARKER, containerId.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // best-effort marker write
        }
        return true;
    }

    static String getContainerId() {
        if (containerId == null) {
            try {
                if (Files.exists(MARKER)) {
                    containerId = new String(Files.readAllBytes(MARKER), StandardCharsets.UTF_8);
                } else {
                    containerId = UUID.randomUUID().toString().substring(0, 8);
                    Files.write(MARKER, containerId.getBytes(StandardCharsets.UTF_8));
                }
            } catch (IOException e) {
                containerId = UUID.randomUUID().toString().substring(0, 8);
            }
        }
        return containerId;
    }
}

// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package org.serverlessbench;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;

/**
 * Detects cold starts with a marker file in /tmp, which lives as long as the container.
 *
 * <p>The first invocation in a container creates the marker and is the only one reported as
 * cold. The marker holds the container's ID, which later invocations read back.
 */
final class ColdStartTracker {

    private static final Path MARKER = Paths.get("/tmp/cold_run");

    /** Cold-start state of one invocation. */
    static final class State {
        final boolean isCold;
        final String containerId;

        private State(boolean isCold, String containerId) {
            this.isCold = isCold;
            this.containerId = containerId;
        }
    }

    private ColdStartTracker() {}

    /**
     * Checks for the marker, creating it when it is missing.
     *
     * <p>Call once per invocation and read both values from the result: any later check in the
     * same container finds the marker and reports a warm start. Synchronized because some
     * platforms run concurrent invocations in one JVM, and only one of them is the cold start.
     *
     * @return whether this invocation is the container's first, and the container's ID
     */
    static synchronized State check() {
        if (Files.exists(MARKER)) {
            String containerId;
            try {
                containerId = new String(Files.readAllBytes(MARKER), StandardCharsets.UTF_8);
            } catch (IOException e) {
                containerId = newContainerId();
            }
            return new State(false, containerId);
        }
        String containerId = newContainerId();
        try {
            Files.write(MARKER, containerId.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // Best effort: without the marker, later invocations also report a cold start.
        }
        return new State(true, containerId);
    }

    private static String newContainerId() {
        return UUID.randomUUID().toString().substring(0, 8);
    }
}

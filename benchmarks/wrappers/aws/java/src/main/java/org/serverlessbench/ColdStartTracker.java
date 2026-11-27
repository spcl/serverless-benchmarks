// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package org.serverlessbench;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;

/** Detects cold starts with a marker file in /tmp, which lives as long as the container. */
final class ColdStartTracker {

    private static final Path MARKER = Paths.get("/tmp/cold_run");

    // Cached so that the ID stays the same even if the marker cannot be read or written
    private static String containerId = null;

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
     * Returns whether this is the container's first invocation, and the container's ID.
     *
     * <p>Synchronized because some platforms run concurrent invocations in one JVM.
     */
    static synchronized State check() {
        if (containerId != null) {
            return new State(false, containerId);
        }
        if (Files.exists(MARKER)) {
            try {
                containerId = new String(Files.readAllBytes(MARKER), StandardCharsets.UTF_8);
            } catch (IOException e) {
                containerId = newContainerId();
            }
            return new State(false, containerId);
        }
        containerId = newContainerId();
        try {
            Files.write(MARKER, containerId.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            // Best effort: without the marker, a new JVM here also reports a cold start
        }
        return new State(true, containerId);
    }

    private static String newContainerId() {
        return UUID.randomUUID().toString().substring(0, 8);
    }
}

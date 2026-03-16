# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package org.serverlessbench;

import com.google.cloud.functions.HttpFunction;
import com.google.cloud.functions.HttpRequest;
import com.google.cloud.functions.HttpResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import function.Function;

import java.io.BufferedWriter;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.stream.Collectors;
import java.time.Instant;

public class Handler implements HttpFunction {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public void service(HttpRequest request, HttpResponse response)
            throws IOException {

        Instant beginTs = Instant.now();

        // Normalize request from GCP HTTP format
        Map<String, Object> normalized = normalizeRequest(request);

        Function function = new Function();
        Map<String, Object> result = function.handler(normalized);

        Instant endTs = Instant.now();

        // Format timestamps as "seconds.microseconds" (SeBS standard)
        String beginStr = formatTimestamp(beginTs);
        String endStr = formatTimestamp(endTs);

        // Get cold start info
        String containerId = ColdStartTracker.getContainerId();
        String coldStartVar = System.getenv("cold_start");
        if (coldStartVar == null) {
            coldStartVar = "";
        }

        Map<String, Object> body = new HashMap<>();
        body.put("begin", beginStr);
        body.put("end", endStr);
        body.put("results_time", 0);
        body.put("result", result);
        body.put("is_cold", ColdStartTracker.isCold());
        body.put("container_id", containerId);
        body.put("cold_start_var", coldStartVar);
        body.put("request_id", request.getFirstHeader("Function-Execution-Id").orElse(""));

        // Write JSON response
        response.setContentType("application/json");
        response.setStatusCode(200);
        BufferedWriter writer = response.getWriter();
        writer.write(MAPPER.writeValueAsString(body));
    }

    private String formatTimestamp(Instant ts) {
        long seconds = ts.getEpochSecond();
        long microseconds = ts.getNano() / 1_000;
        return String.format("%d.%06d", seconds, microseconds);
    }

    private Map<String, Object> normalizeRequest(HttpRequest request)
            throws IOException {

        try {
            Map<String, Object> map = MAPPER.readValue(request.getReader(), Map.class);
            if (map != null) {
                return map;
            }
        } catch (IOException e) {
            // fall through to query parameters
        }

        return new HashMap<>(request.getQueryParameters());
    }
}

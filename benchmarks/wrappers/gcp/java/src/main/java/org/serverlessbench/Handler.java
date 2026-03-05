package org.serverlessbench;

import com.google.cloud.functions.HttpFunction;
import com.google.cloud.functions.HttpRequest;
import com.google.cloud.functions.HttpResponse;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedWriter;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.stream.Collectors;

public class Handler implements HttpFunction {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public void service(HttpRequest request, HttpResponse response)
            throws IOException {

        long beginMs = System.currentTimeMillis();
        long beginNs = System.nanoTime();

        // Normalize request from GCP HTTP format
        Map<String, Object> normalized = normalizeRequest(request);

        Map<String, Object> result = FunctionInvoker.invoke(normalized);

        long endNs = System.nanoTime();
        long endMs = System.currentTimeMillis();

        // Format timestamps as "seconds.microseconds" (SeBS standard)
        String beginStr = formatTimestamp(beginMs, beginNs);
        String endStr = formatTimestamp(endMs, endNs);

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

    private String formatTimestamp(long epochMillis, long nanoTime) {
        long seconds = epochMillis / 1000;
        long microseconds = (nanoTime / 1000) % 1_000_000;
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

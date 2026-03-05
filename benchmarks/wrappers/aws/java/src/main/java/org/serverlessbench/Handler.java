package org.serverlessbench;

import com.amazonaws.services.lambda.runtime.Context;
import com.amazonaws.services.lambda.runtime.RequestHandler;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.HashMap;
import java.util.Map;

public class Handler implements RequestHandler<Map<String, Object>, Map<String, Object>> {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public Map<String, Object> handleRequest(Map<String, Object> event, Context context) {
        long beginMs = System.currentTimeMillis();
        long beginNs = System.nanoTime();
        Map<String, Object> normalized = normalize(event);
        Map<String, Object> result = FunctionInvoker.invoke(normalized);
        long endNs = System.nanoTime();
        long endMs = System.currentTimeMillis();

        // Format timestamps as "seconds.microseconds" like Python
        String beginStr = formatTimestamp(beginMs, beginNs);
        String endStr = formatTimestamp(endMs, endNs);

        // Get or create container ID
        String containerId = ColdStartTracker.getContainerId();

        // Get cold_start environment variable if present
        String coldStartVar = System.getenv("cold_start");
        if (coldStartVar == null) {
            coldStartVar = "";
        }

        Map<String, Object> body = new HashMap<>();
        body.put("begin", beginStr);
        body.put("end", endStr);
        body.put("results_time", 0);
        body.put("is_cold", ColdStartTracker.isCold());
        body.put("result", result);
        body.put("request_id", context != null ? context.getAwsRequestId() : "");
        body.put("cold_start_var", coldStartVar);
        body.put("container_id", containerId);

        Map<String, Object> response = new HashMap<>();
        response.put("statusCode", 200);
        try {
            response.put("body", MAPPER.writeValueAsString(body));
        } catch (Exception e) {
            response.put("body", "{}");
        }

        return response;
    }

    private String formatTimestamp(long epochMillis, long nanoTime) {
        long seconds = epochMillis / 1000;
        // Use nanos for microseconds precision
        long microseconds = (nanoTime / 1000) % 1_000_000;
        return String.format("%d.%06d", seconds, microseconds);
    }

    private Map<String, Object> normalize(Map<String, Object> event) {
        if (event == null) {
            return new HashMap<>();
        }
        Object body = event.get("body");
        if (body instanceof String) {
            try {
                @SuppressWarnings("unchecked")
                Map<String, Object> parsed = MAPPER.readValue((String) body, Map.class);
                return parsed;
            } catch (Exception ignored) {
                // fall back to original event
            }
        }
        return new HashMap<>(event);
    }
}

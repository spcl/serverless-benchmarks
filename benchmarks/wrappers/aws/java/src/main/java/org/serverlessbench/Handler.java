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
        long beginNs = System.nanoTime();
        Map<String, Object> normalized = normalize(event);
        Map<String, Object> result = FunctionInvoker.invoke(normalized);
        long endNs = System.nanoTime();

        Map<String, Object> body = new HashMap<>();
        body.put("begin", beginNs / 1_000_000_000.0);
        body.put("end", endNs / 1_000_000_000.0);
        body.put("compute_time", (endNs - beginNs) / 1_000.0);
        body.put("results_time", 0);
        body.put("result", result);
        body.put("is_cold", ColdStartTracker.isCold());
        body.put("request_id", context != null ? context.getAwsRequestId() : "");

        return body;
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

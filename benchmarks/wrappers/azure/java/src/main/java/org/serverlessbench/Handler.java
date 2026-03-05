package org.serverlessbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.azure.functions.*;
import com.microsoft.azure.functions.annotation.AuthorizationLevel;
import com.microsoft.azure.functions.annotation.FunctionName;
import com.microsoft.azure.functions.annotation.HttpTrigger;
import function.Function;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

public class Handler {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @FunctionName("handler")
    public HttpResponseMessage handleRequest(
        @HttpTrigger(
          name = "req",
          methods = {HttpMethod.GET, HttpMethod.POST},
          authLevel = AuthorizationLevel.ANONYMOUS
        )
        final HttpRequestMessage<Optional<String>> request,
        final ExecutionContext context
    ) {

        long beginMs = System.currentTimeMillis();
        long beginNs = System.nanoTime();
        Map<String, Object> normalized = normalizeRequest(request);
        Function function = new Function();
        Map<String, Object> result = function.handler(normalized);
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
        body.put("result", result);
        body.put("is_cold", ColdStartTracker.isCold());
        body.put("container_id", containerId);
        body.put("cold_start_var", coldStartVar);
        body.put("request_id", context != null ? context.getInvocationId() : "");

        String json = toJson(body);
        return request
                .createResponseBuilder(HttpStatus.OK)
                .header("Content-Type", "application/json")
                .body(json)
                .build();
    }

    private String formatTimestamp(long epochMillis, long nanoTime) {
        long seconds = epochMillis / 1000;
        // Use nanos for microseconds precision
        long microseconds = (nanoTime / 1000) % 1_000_000;
        return String.format("%d.%06d", seconds, microseconds);
    }

    private Map<String, Object> normalizeRequest(HttpRequestMessage<Optional<String>> request) {
        if (request == null) {
            return new HashMap<>();
        }
        Optional<String> body = request.getBody();
        if (body.isPresent()) {
            try {
                @SuppressWarnings("unchecked")
                Map<String, Object> parsed = MAPPER.readValue(body.get(), Map.class);
                return parsed;
            } catch (IOException ignored) {
                // ignore and continue
            }
        }
        return new HashMap<>(request.getQueryParameters());
    }

    private String toJson(Map<String, Object> payload) {
        try {
            return MAPPER.writeValueAsString(payload);
        } catch (IOException e) {
            return "{}";
        }
    }
}

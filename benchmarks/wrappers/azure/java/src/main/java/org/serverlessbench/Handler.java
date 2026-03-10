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
import java.time.Instant;

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

        Instant beginTs = Instant.now();
        Map<String, Object> normalized = normalizeRequest(request);
        Function function = new Function();
        Map<String, Object> result = function.handler(normalized);
        Instant endTs = Instant.now();

        // Format timestamps as "seconds.microseconds" like Python
        String beginStr = formatTimestamp(beginTs);
        String endStr = formatTimestamp(endTs);

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

    private String formatTimestamp(Instant ts) {
        long seconds = ts.getEpochSecond();
        long microseconds = ts.getNano() / 1_000;
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

package org.serverlessbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.azure.functions.*;
import com.microsoft.azure.functions.annotation.AuthorizationLevel;
import com.microsoft.azure.functions.annotation.FunctionName;
import com.microsoft.azure.functions.annotation.HttpTrigger;

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
                            authLevel = AuthorizationLevel.ANONYMOUS)
                    final HttpRequestMessage<Optional<String>> request,
            final ExecutionContext context) {

        long beginNs = System.nanoTime();
        Map<String, Object> normalized = normalizeRequest(request);
        Map<String, Object> result = FunctionInvoker.invoke(normalized);
        long endNs = System.nanoTime();

        Map<String, Object> body = new HashMap<>();
        body.put("begin", beginNs / 1_000_000_000.0);
        body.put("end", endNs / 1_000_000_000.0);
        body.put("compute_time", (endNs - beginNs) / 1_000.0);
        body.put("results_time", 0);
        body.put("result", result);
        body.put("is_cold", ColdStartTracker.isCold());
        body.put("is_cold_worker", ColdStartTracker.isWorkerCold());
        body.put("request_id", context != null ? context.getInvocationId() : "");

        String coldStartVar = System.getenv("cold_start");
        if (coldStartVar != null) {
            body.put("cold_start_var", coldStartVar);
        }

        String json = toJson(body);
        return request
                .createResponseBuilder(HttpStatus.OK)
                .header("Content-Type", "application/json")
                .body(json)
                .build();
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

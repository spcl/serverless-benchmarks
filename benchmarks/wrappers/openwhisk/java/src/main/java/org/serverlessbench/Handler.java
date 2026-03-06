package org.serverlessbench;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;
import java.util.Map;
import java.time.Instant;
import java.time.Duration;
import java.io.File;
import java.io.IOException;

import function.Function;


public class Handler {

    static Type mapType = new TypeToken<Map<String, Object>>(){}.getType();
    static Gson gson = new Gson();

    public static JsonObject main(JsonObject args) {

        Function function = new Function();

        Instant begin = Instant.now();
        Map<String, Object> result = function.handler(gson.fromJson(args, mapType));
        Instant end = Instant.now();

        String containerId = ColdStartTracker.getContainerId();

        // Convert to Unix timestamp in seconds.microseconds
        String formattedBegin = formatTimestamp(begin);
        String formattedEnd = formatTimestamp(end);

        String requestId = System.getenv("__OW_ACTIVATION_ID");
        if (requestId == null) {
            requestId = "";
        }

        // Create result wrapper matching Python format
        JsonObject logData = new JsonObject();
        logData.add("result", gson.toJsonTree(result).getAsJsonObject());

        JsonObject jsonResult = new JsonObject();
        jsonResult.addProperty("begin", formattedBegin);
        jsonResult.addProperty("end", formattedEnd);
        jsonResult.addProperty("request_id", requestId);
        jsonResult.addProperty("results_time", 0);
        jsonResult.addProperty("is_cold", ColdStartTracker.isCold());
        jsonResult.addProperty("container_id", containerId);
        jsonResult.add("result", logData);

        return jsonResult;
    }

    static private String formatTimestamp(Instant ts) {
        long seconds = ts.getEpochSecond();
        long microseconds = ts.getNano() / 1_000;
        return String.format("%d.%06d", seconds, microseconds);
    }

}


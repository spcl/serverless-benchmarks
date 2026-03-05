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

        boolean isCold = false;
        String fileName = "/tmp/cold_run";

        File file = new File(fileName);
        if (!file.exists()) {
            isCold = true;
            try {
                file.createNewFile();
            } catch (IOException e) {
                e.printStackTrace();
            }
        }

        // Convert to Unix timestamp in seconds.microseconds
        String formattedBegin = String.format("%d.%06d", begin.getEpochSecond(), begin.getNano() / 1000);
        String formattedEnd = String.format("%d.%06d", end.getEpochSecond(), end.getNano() / 1000);

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
        jsonResult.addProperty("is_cold", isCold);
        jsonResult.add("result", logData);
        return jsonResult;
    }

}


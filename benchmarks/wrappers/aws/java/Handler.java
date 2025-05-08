import com.amazonaws.services.lambda.runtime.Context;
import com.amazonaws.services.lambda.runtime.RequestHandler;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;

import faas.App;

import java.io.File;
import java.io.IOException;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

public class Handler implements RequestHandler<Map<String, Object>, String> {
    private static final ObjectMapper mapper = new ObjectMapper();

    @Override
    public String handleRequest(Map<String, Object> event, Context context) {

        Map<String, Object> inputData = event;

        // Extract input if trigger is API Gateway (body is a string)
        if (event.containsKey("body") && event.get("body") instanceof String)
            try {
                inputData = mapper.readValue((String) event.get("body"),new TypeReference<Map<String, Object>>() {});
            } catch (IOException e) {
                throw new RuntimeException("Failed to parse JSON body", e);
            }

        App function = new App();

        Instant begin = Instant.now();
        long start_nano = System.nanoTime();

        Map<String, Object> functionOutput = function.handler(inputData);

        long end_nano = System.nanoTime();
        Instant end = Instant.now();

        
        long computeTime = end_nano - start_nano;
        // Detect cold start
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
        String formattedBegin = String.format("%d.%06d", begin.getEpochSecond(), begin.getNano() / 1000); // Convert nanoseconds to microseconds
        String formattedEnd = String.format("%d.%06d", end.getEpochSecond(), end.getNano() / 1000);

 
        Map<String, Object> result = new HashMap<>();
        result.put("begin", formattedBegin); 
        result.put("end", formattedEnd);
        result.put("request_id", context.getAwsRequestId());  
        result.put("compute_time", computeTime);
        result.put("is_cold", isCold);
        result.put("result", functionOutput);
        try {
            return mapper.writeValueAsString(result);
        } catch (IOException e) {
            throw new RuntimeException("Failed to serialize result of benchmark to JSON in Wrapper", e);
        }

    }
}

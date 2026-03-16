// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package function;

import com.github.mustachejava.DefaultMustacheFactory;
import com.github.mustachejava.Mustache;
import com.github.mustachejava.MustacheFactory;

import java.io.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

public class Function {

    private static final DateTimeFormatter DATE_FORMATTER = 
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    
    public Map<String, Object> handler(Map<String, Object> event) {
        try {
            // Get input parameters
            String username = (String) event.getOrDefault("username", "Guest");
            int randomLen = parseRandomLen(event.get("random_len"));
            
            // Generate random numbers
            List<Integer> randomNumbers = generateRandomNumbers(randomLen);
            
            // Get current time
            String currentTime = LocalDateTime.now().format(DATE_FORMATTER);
            
            // Prepare template data
            Map<String, Object> templateData = new HashMap<>();
            templateData.put("username", username);
            templateData.put("cur_time", currentTime);
            templateData.put("random_numbers", randomNumbers);
            
            // Render HTML
            String html = renderTemplate(templateData);
            
            // Return result
            Map<String, Object> result = new HashMap<>();
            result.put("result", html);
            return result;
            
        } catch (Exception e) {
            // Return error as result to avoid crashing
            Map<String, Object> result = new HashMap<>();
            StringWriter sw = new StringWriter();
            PrintWriter pw = new PrintWriter(sw);
            e.printStackTrace(pw);
            result.put("result", "<html><body><h1>Error</h1><pre>" + 
                      sw.toString() + "</pre></body></html>");
            return result;
        }
    }
    
    private int parseRandomLen(Object value) {
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        if (value instanceof String) {
            try {
                return Integer.parseInt((String) value);
            } catch (NumberFormatException e) {
                return 10; // default
            }
        }
        return 10; // default
    }
    
    private List<Integer> generateRandomNumbers(int count) {
        Random random = new Random();
        List<Integer> numbers = new ArrayList<>(count);
        for (int i = 0; i < count; i++) {
            numbers.add(random.nextInt(1000000));
        }
        return numbers;
    }
    
    private String renderTemplate(Map<String, Object> data) throws Exception {
        // Try to load template from classpath
        InputStream templateStream = getClass().getClassLoader()
            .getResourceAsStream("templates/template.html");
        
        if (templateStream == null) {
            throw new IOException("Template not found in classpath");
        }
        
        // Create Mustache factory and compile template
        MustacheFactory mf = new DefaultMustacheFactory();
        Mustache mustache;
        
        try (InputStreamReader reader = new InputStreamReader(templateStream)) {
            mustache = mf.compile(reader, "template");
        }
        
        // Render template
        StringWriter writer = new StringWriter();
        mustache.execute(writer, data).flush();
        return writer.toString();
    }
}

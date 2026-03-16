# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
package function;

import java.util.HashMap;
import java.util.Map;

public class Function {

    public Map<String, Object> handler(Map<String, Object> event) {
        double sleepSeconds = parseSeconds(event.get("sleep"));
        try {
            Thread.sleep((long) (sleepSeconds * 1000));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        Map<String, Object> result = new HashMap<>();
        result.put("result", sleepSeconds);
        return result;
    }

    private double parseSeconds(Object value) {
        if (value instanceof Number) {
            return ((Number) value).doubleValue();
        }
        if (value instanceof String) {
            try {
                return Double.parseDouble((String) value);
            } catch (NumberFormatException ignored) {
                return 0;
            }
        }
        return 0;
    }
}

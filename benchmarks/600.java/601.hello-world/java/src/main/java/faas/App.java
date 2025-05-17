package faas;
import java.util.HashMap;
import java.util.Map;

public class App {
    public Map<String, Object> handler(Map<String, Object> input) {

        Map<String, Object> result = new HashMap<>();
        result.put("Hello", "World");
        return result;
    }
}


package faas;
import com.google.gson.JsonObject;

public class App {
    public JsonObject handler(JsonObject args) {

        JsonObject jsonResult = new JsonObject();
        jsonResult.addProperty("Hello", "World");
        return jsonResult;
    }
}
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import util.SessionBlob;
import util.ShaSecurityProvider;

import java.io.FileReader;
import java.io.IOException;

public class TestFaas {

    public static void main(String[] args) {

//        String currentWorkingDir = System.getProperty("user.dir");
//        System.out.println("Current working directory: " + currentWorkingDir);

        String filePath = "src/test/java/sample_input_valid_token.txt";
//        String filePath = "src/test/java/sample_valid_token.txt";
//        String filePath = "src/test/java/sample_input_null_token.txt";

        JsonObject jsonObject = null;
        try (FileReader reader = new FileReader(filePath)) {
            jsonObject = JsonParser.parseReader(reader).getAsJsonObject();
            System.out.println(jsonObject);
        } catch (IOException e) {
            e.printStackTrace();
        }
        Gson gson = new Gson();

        SessionBlob blob = gson.fromJson(jsonObject, SessionBlob.class);

        ShaSecurityProvider securityProvider = new ShaSecurityProvider();
        SessionBlob validatedBlob = securityProvider.validate(blob);

        JsonObject jsonResult = new JsonObject();
        if (validatedBlob != null)
            jsonResult.addProperty("Authorization-Status", "Authorized");
        else
            jsonResult.addProperty("Authorization-Status", "Unauthorized");

        System.out.println(jsonResult);
    }
}

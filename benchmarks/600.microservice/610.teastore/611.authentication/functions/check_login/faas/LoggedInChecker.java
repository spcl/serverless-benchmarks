package faas;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import util.SessionBlob;
import util.ShaSecurityProvider;

//import jakarta.ws.rs.core.Response;

public class LoggedInChecker {
    public static JsonObject main(JsonObject args) {
        Gson gson = new Gson();
        SessionBlob blob = gson.fromJson(args, SessionBlob.class);

        ShaSecurityProvider securityProvider = new ShaSecurityProvider();
        SessionBlob validatedBlob = securityProvider.validate(blob);

        JsonObject jsonResult = new JsonObject();
        if (validatedBlob != null)
            jsonResult.addProperty("Authorization-Status", "Authorized");
        else
            jsonResult.addProperty("Authorization-Status", "Unauthorized");

// Base version of output in TeaStore is commented:
//        Response.status(Response.Status.OK).entity(new ShaSecurityProvider().validate(blob)).build();

        return jsonResult;
    }


}


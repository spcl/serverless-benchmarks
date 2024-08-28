package faas;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import util.Order;
import util.SessionBlob;
import util.ShaSecurityProvider;
import jakarta.ws.rs.core.Response;


public class LoggedInChecker {
    public static JsonObject main(JsonObject args) {
        Gson gson = new Gson();
        SessionBlob blob = gson.fromJson(args, SessionBlob.class);

        //main code
        blob.setUID(null);
        blob.setSID(null);
        blob.setOrder(new Order());
        blob.getOrderItems().clear();

//        JsonObject jsonBlob = gson.toJsonTree(blob).getAsJsonObject();
//        jsonBlob.addProperty("status", "logout successful");

        Response.status(Response.Status.OK).entity(new ShaSecurityProvider().validate(blob)).build();
        JsonObject jsonBlob = gson.toJsonTree(blob).getAsJsonObject();
        return jsonBlob;

    }
}

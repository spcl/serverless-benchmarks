// package org.example;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

public class Logout {
    public static JsonObject main(JsonObject args) {
        Gson gson = new Gson();
        SessionBlob blob = gson.fromJson(args, SessionBlob.class);

        //main code
        blob.setUID(null);
        blob.setSID(null);
        blob.setOrder(new Order());
        blob.getOrderItems().clear();

        JsonObject jsonBlob = gson.toJsonTree(blob).getAsJsonObject();
        jsonBlob.addProperty("status", "logout successful");
        return jsonBlob;
    }
}


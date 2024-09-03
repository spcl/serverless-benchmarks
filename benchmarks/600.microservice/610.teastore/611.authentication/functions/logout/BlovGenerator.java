// package org.example;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;

//TIP To <b>Run</b> code, press <shortcut actionId="Run"/> or
// click the <icon src="AllIcons.Actions.Execute"/> icon in the gutter.
public class BlovGenerator {
    public static void main(String[] args) {
        Gson gson = new Gson();
        SessionBlob blob = createSessionBlob();

        JsonObject jsonBlob = gson.toJsonTree(blob).getAsJsonObject();
        System.out.println(jsonBlob.toString());
    }

    private static SessionBlob createSessionBlob() {
        SessionBlob blob = new SessionBlob();

        // Set specific UID, SID, and token
        blob.setUID(12345L);
        blob.setSID("session-12345");
        blob.setToken("token-abcde12345");
        blob.setMessage("This is a specific message.");

        // Create an Order with specific values
        Order order = new Order();
        order.setId(1L);
        order.setUserId(101L);
        order.setTime("2024-08-24T12:34:56");
        order.setTotalPriceInCents(1999);
        order.setAddressName("John Doe");
        order.setAddress1("123 Example St.");
        order.setAddress2("Apt 101");
        order.setCreditCardCompany("Visa");
        order.setCreditCardNumber("4111-1111-1111-1111");
        order.setCreditCardExpiryDate("2025-12");

        blob.setOrder(order);

        // Create OrderItems with specific values
        List<OrderItem> orderItems = new ArrayList<>();
        OrderItem item1 = new OrderItem();
        item1.setId(1L);
        item1.setProductId(201L);
        item1.setOrderId(order.getId());
        item1.setQuantity(2);
        item1.setUnitPriceInCents(500);

        OrderItem item2 = new OrderItem();
        item2.setId(2L);
        item2.setProductId(202L);
        item2.setOrderId(order.getId());
        item2.setQuantity(1);
        item2.setUnitPriceInCents(999);

        // Add items to the list
        orderItems.add(item1);
        orderItems.add(item2);

        blob.setOrderItems(orderItems);

        return blob;
    }
}
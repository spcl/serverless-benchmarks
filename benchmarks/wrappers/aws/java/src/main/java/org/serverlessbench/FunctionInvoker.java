package org.serverlessbench;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

final class FunctionInvoker {

    private static final String DEFAULT_CLASS = "function.Function";
    private static final String DEFAULT_METHOD = "handler";

    private FunctionInvoker() {}

    static Map<String, Object> invoke(Map<String, Object> input) {
        try {
            Class<?> fnClass = Class.forName(DEFAULT_CLASS);
            Object instance = fnClass.getDeclaredConstructor().newInstance();
            Method method = fnClass.getMethod(DEFAULT_METHOD, Map.class);
            Object result = method.invoke(instance, input);
            if (result instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> casted = (Map<String, Object>) result;
                return casted;
            }
        } catch (ClassNotFoundException e) {
            return defaultResponse("Function implementation not found");
        } catch (NoSuchMethodException e) {
            return defaultResponse("Function.handler(Map<String,Object>) missing");
        } catch (InvocationTargetException | InstantiationException | IllegalAccessException e) {
            return defaultResponse("Failed to invoke function: " + e.getMessage());
        }
        return defaultResponse("Function returned unsupported type");
    }

    private static Map<String, Object> defaultResponse(String message) {
        Map<String, Object> out = new HashMap<>();
        out.put("output", message);
        return out;
    }
}

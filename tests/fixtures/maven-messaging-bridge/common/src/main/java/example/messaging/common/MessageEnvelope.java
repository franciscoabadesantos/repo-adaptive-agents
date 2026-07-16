package example.messaging.common;

public record MessageEnvelope(String destination, String payload) {}

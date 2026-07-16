package example.messaging.consumer;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.web.client.RestTemplate;

public class MessageConsumer {
    private RestTemplate client;

    @RabbitListener(queues = "messages.queue")
    public void consume(String payload) {
        client.postForObject("http://gateway.local/send", payload, String.class);
    }
}

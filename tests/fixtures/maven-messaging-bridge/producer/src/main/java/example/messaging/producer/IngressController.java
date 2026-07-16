package example.messaging.producer;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class IngressController {
    private RabbitTemplate rabbitTemplate;

    public void submit(String payload) {
        rabbitTemplate.convertAndSend("messages.exchange", "messages.route", payload);
    }
}

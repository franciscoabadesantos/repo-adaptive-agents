package example.messaging.manager;

import org.springframework.web.bind.annotation.RestController;

@RestController
public class ManagerController {
    public String stats() {
        return "rabbitmq_management";
    }
}

package com.example.mpro;

import javax.ws.rs.GET;
import javax.ws.rs.Path;
import javax.ws.rs.Produces;
import javax.ws.rs.core.MediaType;
import org.keycloak.services.resource.RealmResourceProvider;

public class ExampleResourceProvider implements RealmResourceProvider {

    @GET
    @Path("status")
    @Produces(MediaType.APPLICATION_JSON)
    public String status() {
        return "{\"status\":\"ok\"}";
    }

    @Override
    public Object getResource() {
        return this;
    }

    @Override
    public void close() {
    }
}

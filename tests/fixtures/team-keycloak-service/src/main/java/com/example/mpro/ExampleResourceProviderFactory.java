package com.example.mpro;

import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.services.resource.RealmResourceProvider;
import org.keycloak.services.resource.RealmResourceProviderFactory;

public class ExampleResourceProviderFactory implements RealmResourceProviderFactory {

    public static final String ID = "mpro-example";

    @Override
    public RealmResourceProvider create(KeycloakSession session) {
        return new ExampleResourceProvider();
    }

    @Override
    public void init(Config.Scope config) {
    }

    @Override
    public String getId() {
        return ID;
    }

    @Override
    public void close() {
    }
}

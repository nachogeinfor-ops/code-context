package com.example.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Application — Spring Boot entry point for the example REST API.
 *
 * <p>Wires the {@code @SpringBootApplication} auto-configuration onto
 * {@code com.example.api} and boots the embedded servlet container. The
 * routes themselves live in the {@link com.example.api.controllers}
 * package and are picked up by component-scan.
 */
@SpringBootApplication
public class Application {

    private static final Logger log = LoggerFactory.getLogger(Application.class);

    /**
     * main bootstraps the Spring application context.
     */
    public static void main(String[] args) {
        ConfigurableApplicationContext ctx = SpringApplication.run(Application.class, args);
        String port = ctx.getEnvironment().getProperty("server.port", "8080");
        log.info("API listening on :{}", port);
    }
}

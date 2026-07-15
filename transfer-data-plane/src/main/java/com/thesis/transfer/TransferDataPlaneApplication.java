package com.thesis.transfer;

import com.thesis.transfer.config.TransferProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableScheduling
@EnableConfigurationProperties(TransferProperties.class)
@SpringBootApplication
public class TransferDataPlaneApplication {

    public static void main(String[] args) {
        SpringApplication.run(TransferDataPlaneApplication.class, args);
    }
}

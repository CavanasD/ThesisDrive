package com.thesis.transfer.storage;

import com.thesis.transfer.config.TransferProperties;
import io.minio.MinioClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class MinioConfig {
    @Bean
    MinioClient minioClient(TransferProperties properties) {
        var config = properties.minio();
        return MinioClient.builder()
                .endpoint(config.endpoint())
                .credentials(config.accessKey(), config.secretKey())
                .build();
    }
}

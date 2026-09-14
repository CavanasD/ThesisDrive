package com.thesis.transfer.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.nio.file.Path;
import java.time.Duration;
import java.util.List;

@Validated
@ConfigurationProperties(prefix = "transfer")
public record TransferProperties(
        @Min(1) long chunkSize,
        Duration sessionTtl,
        Duration lockTtl,
        Path tempDirectory,
        Duration cleanupInterval,
        @NotBlank String completionStream,
        @Min(1) long completionStreamMaxLength,
        @Valid Minio minio,
        @Valid Security security,
        @Valid Cors cors
) {
    public record Minio(
            @NotBlank String endpoint,
            @NotBlank String bucket,
            @NotBlank String accessKey,
            @NotBlank String secretKey
    ) {}

    public record Security(
            @NotBlank String publicKeyLocation,
            @NotBlank String issuer,
            @NotBlank String audience,
            Duration clockSkew
    ) {}

    public record Cors(@NotEmpty List<String> allowedOrigins) {}
}

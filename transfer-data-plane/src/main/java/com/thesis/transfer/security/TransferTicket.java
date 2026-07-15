package com.thesis.transfer.security;

import java.time.Instant;

public record TransferTicket(
        String taskId,
        String username,
        TransferOperation operation,
        String objectKey,
        long maxSize,
        String expectedSha256,
        Instant expiresAt
) {}

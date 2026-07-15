package com.thesis.transfer.upload;

public record UploadResult(
        String taskId,
        String status,
        String objectKey,
        long size,
        String sha256,
        long offset,
        boolean completed,
        boolean idempotentRetry
) {}

package com.thesis.transfer.session;

import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.web.TransferException;
import org.springframework.http.HttpStatus;
import org.springframework.util.StringUtils;

import java.util.Map;

public record TransferSession(
        String taskId,
        String username,
        TransferOperation operation,
        String objectKey,
        long maxSize,
        String filename,
        String contentType,
        String expectedSha256,
        long offset,
        String status
) {
    public static TransferSession from(Map<String, String> values) {
        try {
            String taskId = required(values, "task_id");
            String username = required(values, "username");
            var operation = TransferOperation.parse(required(values, "operation"));
            String objectKey = required(values, "object_key");
            long maxSize = Long.parseLong(required(values, "max_size"));
            long offset = Long.parseLong(values.getOrDefault("offset", "0"));
            String status = values.getOrDefault("status", "pending");
            return new TransferSession(
                    taskId,
                    username,
                    operation,
                    objectKey,
                    maxSize,
                    blankToNull(values.get("filename")),
                    blankToNull(values.get("content_type")),
                    blankToNull(values.get("expected_sha256")),
                    offset,
                    status
            );
        } catch (NumberFormatException exception) {
            throw new TransferException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "invalid_session",
                    "Redis transfer session contains an invalid number"
            );
        }
    }

    private static String required(Map<String, String> values, String name) {
        String value = values.get(name);
        if (!StringUtils.hasText(value)) {
            throw new TransferException(
                    HttpStatus.INTERNAL_SERVER_ERROR,
                    "invalid_session",
                    "Redis transfer session is missing " + name
            );
        }
        return value;
    }

    private static String blankToNull(String value) {
        return StringUtils.hasText(value) ? value : null;
    }
}

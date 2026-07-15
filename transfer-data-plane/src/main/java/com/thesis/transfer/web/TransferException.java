package com.thesis.transfer.web;

import org.springframework.http.HttpStatus;

public class TransferException extends RuntimeException {
    private final HttpStatus status;
    private final String code;
    private final Long expectedOffset;
    private final Long resourceSize;

    public TransferException(HttpStatus status, String code, String message) {
        this(status, code, message, null, null);
    }

    public TransferException(HttpStatus status, String code, String message, Long expectedOffset) {
        this(status, code, message, expectedOffset, null);
    }

    private TransferException(
            HttpStatus status,
            String code,
            String message,
            Long expectedOffset,
            Long resourceSize
    ) {
        super(message);
        this.status = status;
        this.code = code;
        this.expectedOffset = expectedOffset;
        this.resourceSize = resourceSize;
    }

    public static TransferException rangeNotSatisfiable(long resourceSize, String message) {
        return new TransferException(
                HttpStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                "range_not_satisfiable",
                message,
                null,
                resourceSize
        );
    }

    public HttpStatus status() {
        return status;
    }

    public String code() {
        return code;
    }

    public Long expectedOffset() {
        return expectedOffset;
    }

    public Long resourceSize() {
        return resourceSize;
    }
}

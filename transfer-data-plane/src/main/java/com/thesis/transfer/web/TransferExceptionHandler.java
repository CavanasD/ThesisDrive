package com.thesis.transfer.web;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;

@RestControllerAdvice
public class TransferExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(TransferExceptionHandler.class);

    @ExceptionHandler(TransferException.class)
    ResponseEntity<Map<String, Object>> transferException(TransferException exception) {
        HttpHeaders headers = new HttpHeaders();
        if (exception.expectedOffset() != null) {
            headers.set("Upload-Offset", Long.toString(exception.expectedOffset()));
        }
        if (exception.resourceSize() != null) {
            headers.set(
                    HttpHeaders.CONTENT_RANGE,
                    "bytes */" + exception.resourceSize()
            );
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", exception.code());
        body.put("message", exception.getMessage());
        if (exception.expectedOffset() != null) {
            body.put("expected_offset", exception.expectedOffset());
        }
        return ResponseEntity.status(exception.status()).headers(headers).body(body);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, Object>> unexpected(Exception exception) {
        log.error("Unhandled transfer error", exception);
        return ResponseEntity.internalServerError().body(Map.of(
                "code", "internal_error",
                "message", "The transfer service could not complete the request"
        ));
    }
}

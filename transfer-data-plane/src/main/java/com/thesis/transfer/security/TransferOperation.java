package com.thesis.transfer.security;

import com.thesis.transfer.web.TransferException;
import org.springframework.http.HttpStatus;

import java.util.Locale;

public enum TransferOperation {
    UPLOAD,
    DOWNLOAD;

    public static TransferOperation parse(String value) {
        try {
            return valueOf(value.toUpperCase(Locale.ROOT));
        } catch (RuntimeException exception) {
            throw new TransferException(
                    HttpStatus.FORBIDDEN,
                    "invalid_ticket",
                    "Ticket operation must be upload or download"
            );
        }
    }

    public String wireValue() {
        return name().toLowerCase(Locale.ROOT);
    }
}

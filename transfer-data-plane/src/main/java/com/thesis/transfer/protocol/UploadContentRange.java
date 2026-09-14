package com.thesis.transfer.protocol;

import com.thesis.transfer.web.TransferException;
import org.springframework.http.HttpStatus;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

public record UploadContentRange(long start, long end, long total, boolean empty) {
    private static final Pattern STANDARD = Pattern.compile("^bytes (\\d+)-(\\d+)/(\\d+)$");
    private static final Pattern EMPTY = Pattern.compile("^bytes \\*/0$");

    public static UploadContentRange parse(String value) {
        if (value != null && EMPTY.matcher(value.trim()).matches()) {
            return new UploadContentRange(0, -1, 0, true);
        }
        Matcher matcher = value == null ? null : STANDARD.matcher(value.trim());
        if (matcher == null || !matcher.matches()) {
            throw invalid("Content-Range must be 'bytes start-end/total'");
        }
        try {
            long start = Long.parseLong(matcher.group(1));
            long end = Long.parseLong(matcher.group(2));
            long total = Long.parseLong(matcher.group(3));
            if (total <= 0 || end < start || end >= total) {
                throw invalid("Content-Range bounds are invalid");
            }
            return new UploadContentRange(start, end, total, false);
        } catch (NumberFormatException exception) {
            throw invalid("Content-Range number is too large");
        }
    }

    public long length() {
        return empty ? 0 : end - start + 1;
    }

    public boolean isFinal() {
        return empty || end + 1 == total;
    }

    private static TransferException invalid(String message) {
        return new TransferException(
                HttpStatus.BAD_REQUEST,
                "invalid_content_range",
                message
        );
    }
}

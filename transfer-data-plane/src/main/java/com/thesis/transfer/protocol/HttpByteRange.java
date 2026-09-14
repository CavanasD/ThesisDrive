package com.thesis.transfer.protocol;

import com.thesis.transfer.web.TransferException;

public record HttpByteRange(long start, long end, long resourceSize, boolean partial) {

    public static HttpByteRange parse(String header, long resourceSize) {
        if (resourceSize < 0) {
            throw new IllegalArgumentException("resourceSize must not be negative");
        }
        if (header == null || header.isBlank()) {
            return new HttpByteRange(0, Math.max(-1, resourceSize - 1), resourceSize, false);
        }
        if (resourceSize == 0 || !header.startsWith("bytes=") || header.contains(",")) {
            throw invalid(resourceSize);
        }

        String specification = header.substring("bytes=".length()).trim();
        int delimiter = specification.indexOf('-');
        if (delimiter < 0) {
            throw invalid(resourceSize);
        }

        try {
            String first = specification.substring(0, delimiter).trim();
            String last = specification.substring(delimiter + 1).trim();
            long start;
            long end;
            if (first.isEmpty()) {
                long suffixLength = Long.parseLong(last);
                if (suffixLength <= 0) {
                    throw invalid(resourceSize);
                }
                suffixLength = Math.min(suffixLength, resourceSize);
                start = resourceSize - suffixLength;
                end = resourceSize - 1;
            } else {
                start = Long.parseLong(first);
                end = last.isEmpty() ? resourceSize - 1 : Long.parseLong(last);
                if (start < 0 || start >= resourceSize || end < start) {
                    throw invalid(resourceSize);
                }
                end = Math.min(end, resourceSize - 1);
            }
            return new HttpByteRange(start, end, resourceSize, true);
        } catch (NumberFormatException exception) {
            throw invalid(resourceSize);
        }
    }

    public long length() {
        return end < start ? 0 : end - start + 1;
    }

    public String contentRange() {
        return "bytes " + start + "-" + end + "/" + resourceSize;
    }

    private static TransferException invalid(long resourceSize) {
        return TransferException.rangeNotSatisfiable(
                resourceSize,
                "Only one satisfiable HTTP byte range is supported"
        );
    }
}

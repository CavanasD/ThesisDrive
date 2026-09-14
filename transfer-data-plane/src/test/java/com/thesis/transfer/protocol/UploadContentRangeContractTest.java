package com.thesis.transfer.protocol;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class UploadContentRangeContractTest {
    @Test
    void acceptsCoreEightMebibyteChunkShape() {
        UploadContentRange range = UploadContentRange.parse(
                "bytes 0-8388607/8388609"
        );

        assertEquals(0, range.start());
        assertEquals(8L * 1024 * 1024, range.length());
        assertEquals(8L * 1024 * 1024 + 1, range.total());
    }

    @Test
    void acceptsFrontendEmptyFileShape() {
        UploadContentRange range = UploadContentRange.parse("bytes */0");

        assertTrue(range.empty());
        assertTrue(range.isFinal());
        assertEquals(0, range.length());
    }
}

package com.thesis.transfer.protocol;

import com.thesis.transfer.web.TransferException;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HttpByteRangeTest {
    @Test
    void parsesBoundedRange() {
        HttpByteRange range = HttpByteRange.parse("bytes=100-199", 1000);

        assertEquals(100, range.start());
        assertEquals(199, range.end());
        assertEquals(100, range.length());
        assertEquals("bytes 100-199/1000", range.contentRange());
        assertTrue(range.partial());
    }

    @Test
    void parsesOpenEndedAndSuffixRanges() {
        HttpByteRange openEnded = HttpByteRange.parse("bytes=900-", 1000);
        HttpByteRange suffix = HttpByteRange.parse("bytes=-25", 1000);

        assertEquals(999, openEnded.end());
        assertEquals(975, suffix.start());
        assertEquals(25, suffix.length());
    }

    @Test
    void representsFullAndEmptyObjects() {
        HttpByteRange full = HttpByteRange.parse(null, 10);
        HttpByteRange empty = HttpByteRange.parse(null, 0);

        assertFalse(full.partial());
        assertEquals(10, full.length());
        assertEquals(0, empty.length());
    }

    @Test
    void rejectsMultipleOrUnsatisfiedRanges() {
        assertThrows(
                TransferException.class,
                () -> HttpByteRange.parse("bytes=0-1,3-4", 10)
        );
        TransferException exception = assertThrows(
                TransferException.class,
                () -> HttpByteRange.parse("bytes=10-", 10)
        );
        assertEquals(10, exception.resourceSize());
    }
}

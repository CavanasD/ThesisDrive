package com.thesis.transfer.session;

import com.thesis.transfer.security.TransferOperation;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CoreRedisSessionContractTest {
    @Test
    void parsesExactHashWrittenByDriveCore() {
        var values = new HashMap<>(Map.of(
                "task_id", "task-1",
                "username", "alice",
                "operation", "upload",
                "object_key", "content/files/object-1",
                "max_size", "1234",
                "expected_sha256", "a".repeat(64),
                "offset", "0",
                "status", "pending",
                "created_at", "1700000000",
                "expires_at", "1700086400"
        ));
        values.put("filename", "report.pdf");
        values.put("content_type", "application/pdf");
        TransferSession session = TransferSession.from(values);

        assertEquals("task-1", session.taskId());
        assertEquals(TransferOperation.UPLOAD, session.operation());
        assertEquals("a".repeat(64), session.expectedSha256());
        assertEquals("report.pdf", session.filename());
        assertEquals("application/pdf", session.contentType());
        assertEquals(0, session.offset());
        assertEquals("pending", session.status());
    }
}

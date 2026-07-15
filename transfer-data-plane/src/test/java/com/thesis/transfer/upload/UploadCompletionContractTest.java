package com.thesis.transfer.upload;

import com.thesis.transfer.config.TransferProperties;
import com.thesis.transfer.protocol.UploadContentRange;
import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.security.TransferTicket;
import com.thesis.transfer.session.LockLease;
import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.session.TransferSessionStore;
import com.thesis.transfer.storage.ObjectStorage;
import com.thesis.transfer.storage.StoredObject;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.core.io.buffer.DataBuffer;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UploadCompletionContractTest {
    private static final String EMPTY_SHA256 =
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void usesRedisChecksumAndPublishesCoreCompletionShapeForEmptyFile() throws Exception {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        TempFileService tempFiles = mock(TempFileService.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        Path tempPath = Path.of("build/test-uploads/empty.part");
        var ticket = new TransferTicket(
                "task-empty",
                "alice",
                TransferOperation.UPLOAD,
                "content/files/empty",
                0,
                null,
                Instant.now().plusSeconds(60)
        );
        var session = new TransferSession(
                "task-empty",
                "alice",
                TransferOperation.UPLOAD,
                "content/files/empty",
                0,
                "empty.txt",
                "text/plain",
                EMPTY_SHA256,
                0,
                "pending"
        );
        var lease = new LockLease("task-empty", "lock-token");
        when(sessions.acquire("task-empty")).thenReturn(Mono.just(lease));
        when(sessions.release(lease)).thenReturn(Mono.empty());
        when(sessions.getRequired("task-empty")).thenReturn(Mono.just(session));
        when(sessions.markStatus(eq("task-empty"), eq("finalizing"), anyMap()))
                .thenReturn(Mono.empty());
        when(sessions.recordTerminal(
                eq("task-empty"), eq("completed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());
        when(tempFiles.pathFor("task-empty")).thenReturn(tempPath);
        when(tempFiles.createEmpty(tempPath)).thenReturn(Mono.empty());
        when(tempFiles.verify(tempPath, 0, EMPTY_SHA256))
                .thenReturn(Mono.just(new VerifiedFile(tempPath, 0, EMPTY_SHA256)));
        when(tempFiles.delete(tempPath)).thenReturn(Mono.empty());
        when(storage.put("content/files/empty", tempPath, 0, EMPTY_SHA256))
                .thenReturn(new StoredObject(0, "etag", EMPTY_SHA256));

        var service = new UploadService(
                sessions,
                tempFiles,
                storage,
                properties(),
                new SimpleMeterRegistry()
        );
        UploadResult result = service.upload(
                ticket,
                UploadContentRange.parse("bytes */0"),
                0L,
                EMPTY_SHA256,
                Flux.<DataBuffer>empty()
        ).block();

        assertTrue(result.completed());
        assertEquals(0, result.offset());
        assertEquals(EMPTY_SHA256, result.sha256());
        verify(tempFiles).verify(tempPath, 0, EMPTY_SHA256);

        ArgumentCaptor<Map> eventCaptor = ArgumentCaptor.forClass(Map.class);
        verify(sessions).recordTerminal(
                eq("task-empty"),
                eq("completed"),
                anyMap(),
                eventCaptor.capture()
        );
        Map<String, String> event = eventCaptor.getValue();
        assertTrue(event.containsKey("event_id"));
        assertEquals("task-empty", event.get("task_id"));
        assertEquals("content/files/empty", event.get("object_key"));
        assertEquals("0", event.get("size"));
        assertEquals(EMPTY_SHA256, event.get("sha256"));
        assertEquals("completed", event.get("status"));
    }

    private static TransferProperties properties() {
        return new TransferProperties(
                8L * 1024 * 1024,
                Duration.ofHours(24),
                Duration.ofHours(2),
                Path.of("build/test-uploads"),
                Duration.ofHours(1),
                "transfer:completed",
                1000,
                new TransferProperties.Minio(
                        "http://localhost:9000", "test", "key", "secret"
                ),
                new TransferProperties.Security(
                        "classpath:test.pem", "issuer", "audience", Duration.ofSeconds(30)
                ),
                new TransferProperties.Cors(List.of("http://localhost"))
        );
    }
}

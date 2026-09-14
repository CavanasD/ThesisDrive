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
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DefaultDataBufferFactory;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.nio.file.Path;
import java.nio.file.Files;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;

class UploadServiceRetryTest {
    @TempDir
    Path directory;

    @Test
    void alreadyCommittedChunkReturnsAuthoritativeOffsetWithoutWritingAgain() throws Exception {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        TempFileService tempFiles = mock(TempFileService.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        var properties = properties();
        var service = new UploadService(
                sessions,
                tempFiles,
                storage,
                properties,
                new SimpleMeterRegistry()
        );
        var ticket = new TransferTicket(
                "task-1",
                "alice",
                TransferOperation.UPLOAD,
                "objects/a.bin",
                20,
                null,
                Instant.now().plusSeconds(60)
        );
        var session = new TransferSession(
                "task-1",
                "alice",
                TransferOperation.UPLOAD,
                "objects/a.bin",
                20,
                "a.bin",
                "application/octet-stream",
                null,
                10,
                "receiving"
        );
        var lease = new LockLease("task-1", "lock-token");
        when(sessions.acquire("task-1")).thenReturn(Mono.just(lease));
        when(sessions.release(lease)).thenReturn(Mono.empty());
        when(sessions.getRequired("task-1")).thenReturn(Mono.just(session));

        Flux<DataBuffer> body = Flux.just(
                DefaultDataBufferFactory.sharedInstance.wrap(new byte[10])
        );
        UploadResult result = service.upload(
                ticket,
                UploadContentRange.parse("bytes 0-9/20"),
                10L,
                null,
                body
        ).block();

        assertEquals(10, result.offset());
        assertTrue(result.idempotentRetry());
        verify(tempFiles, never()).write(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any()
        );
        verify(storage, never()).put(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(Path.class),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @Test
    void committedLastChunkResumesFinalizationWithoutWritingChunkAgain() throws Exception {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        TempFileService tempFiles = mock(TempFileService.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        var service = new UploadService(
                sessions,
                tempFiles,
                storage,
                properties(),
                new SimpleMeterRegistry()
        );
        var ticket = new TransferTicket(
                "task-finalizing",
                "alice",
                TransferOperation.UPLOAD,
                "objects/finalizing.bin",
                10,
                null,
                Instant.now().plusSeconds(60)
        );
        var session = new TransferSession(
                "task-finalizing",
                "alice",
                TransferOperation.UPLOAD,
                "objects/finalizing.bin",
                10,
                "finalizing.bin",
                "application/octet-stream",
                null,
                10,
                "finalizing"
        );
        var lease = new LockLease("task-finalizing", "lock-token");
        Path path = directory.resolve("finalizing.part");
        Files.write(path, new byte[10]);
        String sha256 = "01d448afd928065458cf670b60f5a594d735af0172c8a6e4e48b9a2af6b2cf5c";
        when(sessions.acquire("task-finalizing")).thenReturn(Mono.just(lease));
        when(sessions.release(lease)).thenReturn(Mono.empty());
        when(sessions.getRequired("task-finalizing")).thenReturn(Mono.just(session));
        when(sessions.markStatus(eq("task-finalizing"), eq("finalizing"), anyMap()))
                .thenReturn(Mono.empty());
        when(sessions.recordTerminal(
                eq("task-finalizing"), eq("completed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());
        when(tempFiles.pathFor("task-finalizing")).thenReturn(path);
        when(tempFiles.verify(path, 10, null))
                .thenReturn(Mono.just(new VerifiedFile(path, 10, sha256)));
        when(tempFiles.delete(path)).thenReturn(Mono.empty());
        when(storage.put("objects/finalizing.bin", path, 10, sha256))
                .thenReturn(new StoredObject(10, "etag", sha256));

        UploadResult result = service.upload(
                ticket,
                UploadContentRange.parse("bytes 0-9/10"),
                10L,
                null,
                Flux.empty()
        ).block();

        assertTrue(result.completed());
        assertEquals(10, result.offset());
        verify(tempFiles, never()).write(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.any()
        );
        verify(sessions).recordTerminal(
                eq("task-finalizing"), eq("completed"), anyMap(), anyMap()
        );
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
                        "http://localhost:9000",
                        "test",
                        "key",
                        "secret"
                ),
                new TransferProperties.Security(
                        "classpath:test.pem",
                        "issuer",
                        "audience",
                        Duration.ofSeconds(30)
                ),
                new TransferProperties.Cors(List.of("http://localhost"))
        );
    }
}

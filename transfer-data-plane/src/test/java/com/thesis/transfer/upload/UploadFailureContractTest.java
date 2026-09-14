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
import com.thesis.transfer.web.TransferException;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.core.io.buffer.DataBuffer;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UploadFailureContractTest {
    private static final String EMPTY_SHA256 =
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void objectStoreFailureCleansUpBeforePublishingFailedTerminalState() throws Exception {
        Fixture fixture = fixture("store-failure");
        when(fixture.storage().put(
                fixture.ticket().objectKey(), fixture.path(), 0, EMPTY_SHA256
        )).thenThrow(new IOException("MinIO unavailable"));
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());

        TransferException failure = assertThrows(
                TransferException.class,
                () -> upload(fixture).block()
        );

        assertEquals("object_store_failure", failure.code());
        ArgumentCaptor<Map> fields = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map> event = ArgumentCaptor.forClass(Map.class);
        verify(fixture.sessions()).recordTerminal(
                eq(fixture.ticket().taskId()),
                eq("failed"),
                fields.capture(),
                event.capture()
        );
        assertEquals("object_store_failure", fields.getValue().get("error"));
        assertEquals("failed", event.getValue().get("status"));
        assertEquals("object_store_failure", event.getValue().get("error"));
        assertFalse(fields.getValue().containsKey("orphaned"));
        verify(fixture.storage()).delete(fixture.ticket().objectKey());
        verify(fixture.tempFiles()).delete(fixture.path());
    }

    @Test
    void exhaustedCompletionRetriesKeepObjectAndTempFileForRecovery() throws Exception {
        Fixture fixture = fixture("completion-failure");
        when(fixture.storage().put(
                fixture.ticket().objectKey(), fixture.path(), 0, EMPTY_SHA256
        )).thenReturn(new StoredObject(0, "etag", EMPTY_SHA256));
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("completed"), anyMap(), anyMap()
        )).thenReturn(Mono.error(new IOException("Redis unavailable")));
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());

        TransferException failure = assertThrows(
                TransferException.class,
                () -> upload(fixture).block()
        );

        assertEquals("completion_persistence_failed", failure.code());
        verify(fixture.sessions(), times(3)).recordTerminal(
                eq(fixture.ticket().taskId()), eq("completed"), anyMap(), anyMap()
        );
        verify(fixture.storage(), never()).delete(fixture.ticket().objectKey());
        verify(fixture.sessions(), never()).recordTerminal(
                eq(fixture.ticket().taskId()),
                eq("failed"),
                anyMap(),
                anyMap()
        );
        verify(fixture.tempFiles(), never()).delete(fixture.path());
    }

    @Test
    void lostCompletionResponseReconcilesCompletedStateWithoutDeletingObject() throws Exception {
        Fixture fixture = fixture("completion-reconciled");
        TransferSession completed = new TransferSession(
                fixture.session().taskId(),
                fixture.session().username(),
                fixture.session().operation(),
                fixture.session().objectKey(),
                fixture.session().maxSize(),
                fixture.session().filename(),
                fixture.session().contentType(),
                fixture.session().expectedSha256(),
                fixture.session().maxSize(),
                "completed"
        );
        when(fixture.sessions().getRequired(fixture.ticket().taskId()))
                .thenReturn(Mono.just(fixture.session()), Mono.just(completed));
        when(fixture.storage().put(
                fixture.ticket().objectKey(), fixture.path(), 0, EMPTY_SHA256
        )).thenReturn(new StoredObject(0, "etag", EMPTY_SHA256));
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("completed"), anyMap(), anyMap()
        )).thenReturn(Mono.error(new IOException("response lost")));

        UploadResult result = upload(fixture).block();

        assertTrue(result.completed());
        assertTrue(result.idempotentRetry());
        verify(fixture.sessions(), times(3)).recordTerminal(
                eq(fixture.ticket().taskId()), eq("completed"), anyMap(), anyMap()
        );
        verify(fixture.storage(), never()).delete(fixture.ticket().objectKey());
        verify(fixture.sessions(), never()).recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        );
        verify(fixture.tempFiles()).delete(fixture.path());
    }

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void failedCleanupMarksPotentialOrphanInStateAndEvent() throws Exception {
        Fixture fixture = fixture("orphaned-store-failure");
        when(fixture.storage().put(
                fixture.ticket().objectKey(), fixture.path(), 0, EMPTY_SHA256
        )).thenThrow(new IOException("MinIO response lost"));
        org.mockito.Mockito.doThrow(new IOException("cleanup unavailable"))
                .when(fixture.storage()).delete(fixture.ticket().objectKey());
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());

        TransferException failure = assertThrows(
                TransferException.class,
                () -> upload(fixture).block()
        );

        assertEquals("object_store_failure", failure.code());
        ArgumentCaptor<Map> fields = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map> event = ArgumentCaptor.forClass(Map.class);
        verify(fixture.sessions()).recordTerminal(
                eq(fixture.ticket().taskId()),
                eq("failed"),
                fields.capture(),
                event.capture()
        );
        assertEquals("true", fields.getValue().get("orphaned"));
        assertEquals("true", event.getValue().get("orphaned"));
    }

    @Test
    void blockedMetadataBecomesTerminalWithoutTouchingObjectStorage() throws Exception {
        Fixture fixture = fixture("blocked-metadata");
        TransferSession blocked = new TransferSession(
                fixture.session().taskId(),
                fixture.session().username(),
                fixture.session().operation(),
                fixture.session().objectKey(),
                fixture.session().maxSize(),
                "payload.php",
                "text/plain",
                fixture.session().expectedSha256(),
                0,
                "pending"
        );
        when(fixture.sessions().getRequired(fixture.ticket().taskId()))
                .thenReturn(Mono.just(blocked));
        when(fixture.sessions().recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        )).thenReturn(Mono.empty());

        TransferException failure = assertThrows(
                TransferException.class,
                () -> upload(fixture).block()
        );

        assertEquals("blocked_file_type", failure.code());
        verify(fixture.sessions()).recordTerminal(
                eq(fixture.ticket().taskId()), eq("failed"), anyMap(), anyMap()
        );
        verify(fixture.storage(), never()).put(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(Path.class),
                org.mockito.ArgumentMatchers.anyLong(),
                org.mockito.ArgumentMatchers.anyString()
        );
        verify(fixture.tempFiles()).delete(fixture.path());
    }

    private static Mono<UploadResult> upload(Fixture fixture) {
        return fixture.service().upload(
                fixture.ticket(),
                UploadContentRange.parse("bytes */0"),
                0L,
                EMPTY_SHA256,
                Flux.<DataBuffer>empty()
        );
    }

    private static Fixture fixture(String suffix) {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        TempFileService tempFiles = mock(TempFileService.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        String taskId = "task-" + suffix;
        Path path = Path.of("build/test-uploads/" + taskId + ".part");
        TransferTicket ticket = new TransferTicket(
                taskId,
                "alice",
                TransferOperation.UPLOAD,
                "content/files/" + suffix,
                0,
                null,
                Instant.now().plusSeconds(60)
        );
        TransferSession session = new TransferSession(
                taskId,
                "alice",
                TransferOperation.UPLOAD,
                ticket.objectKey(),
                0,
                suffix + ".txt",
                "text/plain",
                EMPTY_SHA256,
                0,
                "pending"
        );
        LockLease lease = new LockLease(taskId, "lock-token");
        when(sessions.acquire(taskId)).thenReturn(Mono.just(lease));
        when(sessions.release(lease)).thenReturn(Mono.empty());
        when(sessions.getRequired(taskId)).thenReturn(Mono.just(session));
        when(sessions.markStatus(eq(taskId), eq("finalizing"), anyMap()))
                .thenReturn(Mono.empty());
        when(tempFiles.pathFor(taskId)).thenReturn(path);
        when(tempFiles.createEmpty(path)).thenReturn(Mono.empty());
        when(tempFiles.verify(path, 0, EMPTY_SHA256))
                .thenReturn(Mono.just(new VerifiedFile(path, 0, EMPTY_SHA256)));
        when(tempFiles.delete(path)).thenReturn(Mono.empty());

        UploadService service = new UploadService(
                sessions,
                tempFiles,
                storage,
                properties(),
                new SimpleMeterRegistry()
        );
        return new Fixture(sessions, tempFiles, storage, service, ticket, session, path);
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

    private record Fixture(
            TransferSessionStore sessions,
            TempFileService tempFiles,
            ObjectStorage storage,
            UploadService service,
            TransferTicket ticket,
            TransferSession session,
            Path path
    ) {
    }
}

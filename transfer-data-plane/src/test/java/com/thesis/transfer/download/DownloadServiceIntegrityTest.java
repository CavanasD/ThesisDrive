package com.thesis.transfer.download;

import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.security.TransferTicket;
import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.session.TransferSessionStore;
import com.thesis.transfer.storage.ObjectStorage;
import com.thesis.transfer.storage.StoredObject;
import com.thesis.transfer.web.TransferException;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class DownloadServiceIntegrityTest {
    @Test
    void rejectsMissingObjectChecksumWhenTicketRequiresOne() throws Exception {
        String sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        TransferTicket ticket = new TransferTicket(
                "task-download",
                "alice",
                TransferOperation.DOWNLOAD,
                "objects/1",
                1,
                sha256,
                Instant.now().plusSeconds(60)
        );
        TransferSession session = new TransferSession(
                "task-download",
                "alice",
                TransferOperation.DOWNLOAD,
                "objects/1",
                1,
                "notes.txt",
                "text/plain",
                sha256,
                0,
                "ready"
        );
        when(sessions.getRequired("task-download")).thenReturn(Mono.just(session));
        when(storage.stat("objects/1")).thenReturn(new StoredObject(1, "etag", null));
        DownloadService service = new DownloadService(
                sessions,
                storage,
                new SimpleMeterRegistry()
        );

        TransferException exception = assertThrows(
                TransferException.class,
                () -> service.prepare(ticket, null).block()
        );

        assertEquals("object_sha256_mismatch", exception.code());
    }
}

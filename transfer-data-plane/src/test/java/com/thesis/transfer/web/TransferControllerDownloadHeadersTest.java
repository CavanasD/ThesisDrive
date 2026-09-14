package com.thesis.transfer.web;

import com.thesis.transfer.download.DownloadService;
import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.security.TransferTicket;
import com.thesis.transfer.security.TransferTicketService;
import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.session.TransferSessionStore;
import com.thesis.transfer.storage.ObjectStorage;
import com.thesis.transfer.storage.StoredObject;
import com.thesis.transfer.upload.UploadService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.MediaType;
import org.springframework.mock.http.server.reactive.MockServerHttpResponse;
import org.springframework.security.oauth2.jwt.Jwt;
import reactor.core.publisher.Mono;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.Arrays;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TransferControllerDownloadHeadersTest {
    @Test
    void downloadUsesSanitizedRedisFilenameAndContentType() throws Exception {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        TransferTicketService tickets = mock(TransferTicketService.class);
        UploadService uploads = mock(UploadService.class);
        Jwt jwt = mock(Jwt.class);
        TransferTicket ticket = new TransferTicket(
                "task-download",
                "alice",
                TransferOperation.DOWNLOAD,
                "content/files/object",
                0,
                null,
                Instant.now().plusSeconds(60)
        );
        TransferSession session = new TransferSession(
                "task-download",
                "alice",
                TransferOperation.DOWNLOAD,
                "content/files/object",
                0,
                "../../报告\r\nInjected: yes.txt",
                "text/plain",
                null,
                0,
                "ready"
        );
        when(tickets.require(jwt, "task-download", TransferOperation.DOWNLOAD))
                .thenReturn(ticket);
        when(sessions.getRequired("task-download")).thenReturn(Mono.just(session));
        when(sessions.markStatus("task-download", "completed", Map.of()))
                .thenReturn(Mono.empty());
        when(storage.stat("content/files/object"))
                .thenReturn(new StoredObject(0, "etag", null));
        DownloadService downloads = new DownloadService(
                sessions,
                storage,
                new SimpleMeterRegistry()
        );
        TransferController controller = new TransferController(tickets, uploads, downloads);
        MockServerHttpResponse response = new MockServerHttpResponse();

        controller.download("task-download", jwt, null, response).block();

        assertEquals(MediaType.TEXT_PLAIN, response.getHeaders().getContentType());
        assertEquals(
                "报告__Injected: yes.txt",
                response.getHeaders().getContentDisposition().getFilename()
        );
        String disposition = response.getHeaders().getFirst("Content-Disposition");
        assertNotNull(disposition);
        assertFalse(disposition.contains("\r"));
        assertFalse(disposition.contains("\n"));
        assertEquals("nosniff", response.getHeaders().getFirst("X-Content-Type-Options"));
    }

    @Test
    void fullDownloadMarksSessionCompletedAfterResponseStreamSucceeds() throws Exception {
        byte[] content = new byte[]{1, 2, 3, 4};
        DownloadFixture fixture = fixture(content);

        fixture.controller().download(
                fixture.ticket().taskId(), fixture.jwt(), null, fixture.response()
        ).block();

        assertArrayEquals(content, responseBody(fixture.response()));
        verify(fixture.sessions()).markStatus(
                fixture.ticket().taskId(), "completed", Map.of()
        );
    }

    @Test
    void rangeDownloadMarksSessionCompletedAfterPartialResponseStreamSucceeds() throws Exception {
        byte[] content = new byte[]{1, 2, 3, 4};
        DownloadFixture fixture = fixture(content);

        fixture.controller().download(
                fixture.ticket().taskId(), fixture.jwt(), "bytes=1-2", fixture.response()
        ).block();

        assertEquals(206, fixture.response().getStatusCode().value());
        assertArrayEquals(
                new byte[]{2, 3},
                responseBody(fixture.response())
        );
        verify(fixture.sessions()).markStatus(
                fixture.ticket().taskId(), "completed", Map.of()
        );
    }

    @Test
    void responseStreamFailureDoesNotMarkSessionCompleted() throws Exception {
        DownloadFixture fixture = fixture(new byte[]{1});
        InputStream failingStream = new InputStream() {
            @Override
            public int read() throws IOException {
                throw new IOException("stream interrupted");
            }
        };
        doReturn(failingStream).when(fixture.storage()).open(
                eq(fixture.ticket().objectKey()), anyLong(), anyLong()
        );

        assertThrows(
                RuntimeException.class,
                () -> fixture.controller().download(
                        fixture.ticket().taskId(),
                        fixture.jwt(),
                        null,
                        fixture.response()
                ).block()
        );

        verify(fixture.sessions(), never()).markStatus(
                eq(fixture.ticket().taskId()), eq("completed"), anyMap()
        );
    }

    private static DownloadFixture fixture(byte[] content) throws Exception {
        TransferSessionStore sessions = mock(TransferSessionStore.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        TransferTicketService tickets = mock(TransferTicketService.class);
        UploadService uploads = mock(UploadService.class);
        Jwt jwt = mock(Jwt.class);
        TransferTicket ticket = new TransferTicket(
                "task-stream",
                "alice",
                TransferOperation.DOWNLOAD,
                "content/files/stream",
                content.length,
                null,
                Instant.now().plusSeconds(60)
        );
        TransferSession session = new TransferSession(
                ticket.taskId(),
                ticket.username(),
                ticket.operation(),
                ticket.objectKey(),
                ticket.maxSize(),
                "stream.bin",
                "application/octet-stream",
                null,
                0,
                "ready"
        );
        when(tickets.require(jwt, ticket.taskId(), TransferOperation.DOWNLOAD))
                .thenReturn(ticket);
        when(sessions.getRequired(ticket.taskId())).thenReturn(Mono.just(session));
        when(sessions.markStatus(ticket.taskId(), "completed", Map.of()))
                .thenReturn(Mono.empty());
        when(storage.stat(ticket.objectKey()))
                .thenReturn(new StoredObject(content.length, "etag", null));
        when(storage.open(eq(ticket.objectKey()), anyLong(), anyLong()))
                .thenAnswer(invocation -> {
                    int offset = Math.toIntExact(invocation.getArgument(1, Long.class));
                    int length = Math.toIntExact(invocation.getArgument(2, Long.class));
                    return new ByteArrayInputStream(
                            Arrays.copyOfRange(content, offset, offset + length)
                    );
                });
        DownloadService downloads = new DownloadService(
                sessions,
                storage,
                new SimpleMeterRegistry()
        );
        TransferController controller = new TransferController(tickets, uploads, downloads);
        return new DownloadFixture(
                sessions,
                storage,
                controller,
                ticket,
                jwt,
                new MockServerHttpResponse()
        );
    }

    private static byte[] responseBody(MockServerHttpResponse response) {
        DataBuffer buffer = DataBufferUtils.join(response.getBody()).block();
        if (buffer == null) {
            return new byte[0];
        }
        try {
            byte[] body = new byte[buffer.readableByteCount()];
            buffer.read(body);
            return body;
        } finally {
            DataBufferUtils.release(buffer);
        }
    }

    private record DownloadFixture(
            TransferSessionStore sessions,
            ObjectStorage storage,
            TransferController controller,
            TransferTicket ticket,
            Jwt jwt,
            MockServerHttpResponse response
    ) {
    }
}

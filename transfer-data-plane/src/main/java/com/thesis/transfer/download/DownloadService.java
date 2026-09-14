package com.thesis.transfer.download;

import com.thesis.transfer.protocol.HttpByteRange;
import com.thesis.transfer.security.TransferTicket;
import com.thesis.transfer.session.TransferSessionStore;
import com.thesis.transfer.storage.ObjectStorage;
import com.thesis.transfer.storage.StoredObject;
import com.thesis.transfer.upload.UploadService;
import com.thesis.transfer.web.TransferException;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.core.io.buffer.DefaultDataBufferFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.io.IOException;
import java.io.InputStream;
import java.util.Map;

@Service
public class DownloadService {
    private static final int READ_BUFFER_SIZE = 64 * 1024;

    private final TransferSessionStore sessions;
    private final ObjectStorage storage;
    private final Counter downloadedBytes;

    public DownloadService(
            TransferSessionStore sessions,
            ObjectStorage storage,
            MeterRegistry meters
    ) {
        this.sessions = sessions;
        this.storage = storage;
        this.downloadedBytes = meters.counter("transfer.download.bytes");
    }

    public Mono<DownloadPlan> prepare(TransferTicket ticket, String rangeHeader) {
        return sessions.getRequired(ticket.taskId())
                .doOnNext(session -> UploadService.validateSession(session, ticket))
                .flatMap(session -> Mono.fromCallable(() -> storage.stat(ticket.objectKey()))
                        .subscribeOn(Schedulers.boundedElastic())
                        .map(object -> createPlan(
                                ticket,
                                session.expectedSha256(),
                                session.filename(),
                                session.contentType(),
                                object,
                                rangeHeader
                        )));
    }

    public Mono<Void> markCompleted(TransferTicket ticket) {
        return sessions.markStatus(ticket.taskId(), "completed", Map.of());
    }

    private DownloadPlan createPlan(
            TransferTicket ticket,
            String sessionExpectedSha256,
            String filename,
            String contentType,
            StoredObject object,
            String rangeHeader
    ) {
        if (object.size() != ticket.maxSize()) {
            throw new TransferException(
                    HttpStatus.CONFLICT,
                    "object_size_mismatch",
                    "Stored object size does not match the transfer ticket"
            );
        }
        String expectedSha256 = ticket.expectedSha256() != null
                ? ticket.expectedSha256()
                : sessionExpectedSha256;
        if (expectedSha256 != null
                && (object.sha256() == null
                || !expectedSha256.equalsIgnoreCase(object.sha256()))) {
            throw new TransferException(
                    HttpStatus.CONFLICT,
                    "object_sha256_mismatch",
                    "Stored object SHA-256 metadata is missing or does not match the ticket"
            );
        }

        HttpByteRange range = HttpByteRange.parse(rangeHeader, object.size());
        Flux<DataBuffer> content = range.length() == 0
                ? Flux.empty()
                : DataBufferUtils.readInputStream(
                        () -> open(ticket.objectKey(), range.start(), range.length()),
                        DefaultDataBufferFactory.sharedInstance,
                        READ_BUFFER_SIZE
                )
                .subscribeOn(Schedulers.boundedElastic())
                .doOnNext(buffer -> downloadedBytes.increment(buffer.readableByteCount()));
        String effectiveSha256 = object.sha256() != null
                ? object.sha256()
                : expectedSha256;
        return new DownloadPlan(
                object,
                effectiveSha256,
                filename,
                contentType,
                range,
                content
        );
    }

    private InputStream open(String objectKey, long offset, long length) throws IOException {
        try {
            return storage.open(objectKey, offset, length);
        } catch (Exception exception) {
            throw new IOException("Unable to open MinIO object", exception);
        }
    }
}

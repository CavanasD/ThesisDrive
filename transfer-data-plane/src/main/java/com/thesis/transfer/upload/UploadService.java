package com.thesis.transfer.upload;

import com.thesis.transfer.config.TransferProperties;
import com.thesis.transfer.protocol.UploadContentRange;
import com.thesis.transfer.security.TransferTicket;
import com.thesis.transfer.session.LockLease;
import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.session.TransferSessionStore;
import com.thesis.transfer.storage.ObjectStorage;
import com.thesis.transfer.web.TransferException;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import reactor.util.retry.Retry;

import java.nio.file.Path;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

@Service
public class UploadService {
    private final TransferSessionStore sessions;
    private final TempFileService tempFiles;
    private final ObjectStorage storage;
    private final TransferProperties properties;
    private final Counter uploadedBytes;
    private final Counter completedUploads;

    public UploadService(
            TransferSessionStore sessions,
            TempFileService tempFiles,
            ObjectStorage storage,
            TransferProperties properties,
            MeterRegistry meters
    ) {
        this.sessions = sessions;
        this.tempFiles = tempFiles;
        this.storage = storage;
        this.properties = properties;
        this.uploadedBytes = meters.counter("transfer.upload.bytes");
        this.completedUploads = meters.counter("transfer.upload.completed");
    }

    public Mono<TransferSession> status(TransferTicket ticket) {
        return sessions.getRequired(ticket.taskId())
                .doOnNext(session -> validateSession(session, ticket));
    }

    public Mono<UploadResult> upload(
            TransferTicket ticket,
            UploadContentRange range,
            Long contentLength,
            String chunkSha256,
            Flux<DataBuffer> body
    ) {
        validateRequest(ticket, range, contentLength, chunkSha256);
        return sessions.acquire(ticket.taskId())
                .flatMap(lease -> Mono.usingWhen(
                        Mono.just(lease),
                        ignored -> uploadLocked(
                                ticket,
                                range,
                                normalizeSha256(chunkSha256),
                                body
                        ),
                        sessions::release,
                        (ignored, error) -> sessions.release(lease),
                        sessions::release
                ));
    }

    private Mono<UploadResult> uploadLocked(
            TransferTicket ticket,
            UploadContentRange range,
            String chunkSha256,
            Flux<DataBuffer> body
    ) {
        return sessions.getRequired(ticket.taskId())
                .flatMap(session -> {
                    validateSession(session, ticket);
                    if ("completed".equalsIgnoreCase(session.status())) {
                        return Mono.just(result(
                                ticket,
                                "completed",
                                ticket.maxSize(),
                                session.expectedSha256(),
                                true,
                                true
                        ));
                    }
                    if ("failed".equalsIgnoreCase(session.status())) {
                        return Mono.error(new TransferException(
                                HttpStatus.CONFLICT,
                                "transfer_failed",
                                "This transfer is terminally failed; request a new ticket"
                        ));
                    }
                    try {
                        UploadContentPolicy.validateMetadata(session);
                    } catch (TransferException exception) {
                        return failUpload(
                                ticket,
                                tempFiles.pathFor(ticket.taskId()),
                                exception,
                                false
                        );
                    }
                    if (range.empty()) {
                        return uploadEmpty(ticket, session);
                    }
                    if (range.end() < session.offset()) {
                        if (session.offset() == ticket.maxSize()) {
                            return finalizeUpload(
                                    ticket,
                                    tempFiles.pathFor(ticket.taskId()),
                                    session
                            );
                        }
                        return Mono.just(result(
                                ticket,
                                session.status(),
                                session.offset(),
                                session.expectedSha256(),
                                session.offset() == ticket.maxSize(),
                                true
                        ));
                    }
                    if (range.start() != session.offset()) {
                        return Mono.error(offsetConflict(session.offset()));
                    }

                    Path path = tempFiles.pathFor(ticket.taskId());
                    return tempFiles.write(
                                    path,
                                    range.start(),
                                    range.length(),
                                    chunkSha256,
                                    body
                            )
                            .doOnNext(written -> uploadedBytes.increment(written.bytesWritten()))
                            .flatMap(written -> advanceAndMaybeFinalize(
                                    ticket,
                                    range,
                                    path,
                                    session
                            ));
                });
    }

    private Mono<UploadResult> uploadEmpty(
            TransferTicket ticket,
            TransferSession session
    ) {
        if (session.offset() != 0) {
            return Mono.error(offsetConflict(session.offset()));
        }
        Path path = tempFiles.pathFor(ticket.taskId());
        return tempFiles.createEmpty(path)
                .then(finalizeUpload(ticket, path, session));
    }

    private Mono<UploadResult> advanceAndMaybeFinalize(
            TransferTicket ticket,
            UploadContentRange range,
            Path path,
            TransferSession session
    ) {
        long newOffset = range.end() + 1;
        return sessions.compareAndSetOffset(ticket.taskId(), range.start(), newOffset)
                .flatMap(actualOffset -> {
                    if (actualOffset != newOffset) {
                        return Mono.error(offsetConflict(actualOffset));
                    }
                    if (newOffset == ticket.maxSize()) {
                        return finalizeUpload(ticket, path, session);
                    }
                    return Mono.just(result(
                            ticket,
                            "receiving",
                            newOffset,
                            null,
                            false,
                            false
                    ));
                });
    }

    private Mono<UploadResult> finalizeUpload(
            TransferTicket ticket,
            Path path,
            TransferSession session
    ) {
        AtomicBoolean objectPutAttempted = new AtomicBoolean();
        AtomicReference<VerifiedFile> verifiedFile = new AtomicReference<>();
        return sessions.markStatus(ticket.taskId(), "finalizing", Map.of())
                .then(tempFiles.verify(path, ticket.maxSize(), session.expectedSha256()))
                .flatMap(file -> Mono.fromCallable(() -> {
                            UploadContentPolicy.validateMagic(file.path(), file.size());
                            verifiedFile.set(file);
                            return file;
                        })
                        .subscribeOn(Schedulers.boundedElastic()))
                .flatMap(file -> Mono.fromCallable(() -> {
                            objectPutAttempted.set(true);
                            return storage.put(
                                    ticket.objectKey(),
                                    file.path(),
                                    file.size(),
                                    file.sha256()
                            );
                        })
                        .subscribeOn(Schedulers.boundedElastic())
                        .onErrorMap(error -> error instanceof TransferException
                                ? error
                                : new TransferException(
                                        HttpStatus.BAD_GATEWAY,
                                        "object_store_failure",
                                        "Object storage could not persist the upload"
                        ))
                        .flatMap(stored -> {
                            if (stored.size() != file.size()) {
                                return Mono.error(new TransferException(
                                        HttpStatus.BAD_GATEWAY,
                                        "object_size_mismatch",
                                        "MinIO stored an unexpected object size"
                                ));
                            }
                            if (stored.sha256() == null
                                    || !stored.sha256().equalsIgnoreCase(file.sha256())) {
                                return Mono.error(new TransferException(
                                        HttpStatus.BAD_GATEWAY,
                                        "object_sha256_mismatch",
                                        "MinIO stored unexpected SHA-256 metadata"
                                ));
                            }
                            Map<String, String> completion = completionEvent(ticket, file);
                            Map<String, String> completedFields = new HashMap<>();
                            completedFields.put("offset", Long.toString(file.size()));
                            completedFields.put("size", Long.toString(file.size()));
                            completedFields.put("sha256", file.sha256());
                            return recordTerminalWithRetry(
                                            ticket.taskId(),
                                            "completed",
                                            completedFields,
                                            completion
                                    )
                                    .onErrorMap(error -> new TransferException(
                                            HttpStatus.SERVICE_UNAVAILABLE,
                                            "completion_persistence_failed",
                                            "Upload bytes were stored but completion could not be recorded"
                                    ))
                                    .then(Mono.defer(() -> tempFiles.delete(path)
                                            .onErrorResume(cleanupError -> Mono.empty())))
                                    .thenReturn(result(
                                            ticket,
                                            "completed",
                                            file.size(),
                                            file.sha256(),
                                            true,
                                            false
                                    ));
                        }))
                .onErrorResume(error -> {
                    TransferException exception = normalizeFinalizeError(error);
                    if (objectPutAttempted.get()
                            && "completion_persistence_failed".equals(exception.code())) {
                        return reconcileCompletion(
                                ticket,
                                path,
                                verifiedFile.get(),
                                exception
                        );
                    }
                    return failUpload(
                            ticket,
                            path,
                            exception,
                            objectPutAttempted.get()
                    );
                })
                .doOnSuccess(ignored -> completedUploads.increment());
    }

    private Mono<UploadResult> reconcileCompletion(
            TransferTicket ticket,
            Path path,
            VerifiedFile file,
            TransferException persistenceFailure
    ) {
        return sessions.getRequired(ticket.taskId())
                .flatMap(current -> {
                    validateSession(current, ticket);
                    if (!"completed".equalsIgnoreCase(current.status())) {
                        return Mono.error(persistenceFailure);
                    }
                    String sha256 = file == null
                            ? current.expectedSha256()
                            : file.sha256();
                    return tempFiles.delete(path)
                            .onErrorResume(cleanupError -> Mono.empty())
                            .thenReturn(result(
                                    ticket,
                                    "completed",
                                    ticket.maxSize(),
                                    sha256,
                                    true,
                                    true
                            ));
                })
                .onErrorResume(error -> Mono.error(persistenceFailure));
    }

    private Mono<UploadResult> failUpload(
            TransferTicket ticket,
            Path path,
            TransferException exception,
            boolean objectStored
    ) {
        AtomicBoolean orphaned = new AtomicBoolean();
        Mono<Void> cleanupObject = objectStored
                ? Mono.fromRunnable(() -> {
                            try {
                                storage.delete(ticket.objectKey());
                            } catch (Exception cleanupError) {
                                throw new RuntimeException(cleanupError);
                            }
                        })
                        .subscribeOn(Schedulers.boundedElastic())
                        .onErrorResume(cleanupError -> {
                            orphaned.set(true);
                            return Mono.empty();
                        })
                        .then()
                : Mono.empty();

        return cleanupObject.then(Mono.defer(() -> {
                    Map<String, String> fields = new HashMap<>();
                    fields.put("error", exception.code());
                    Map<String, String> event = failureEvent(ticket, exception.code());
                    if (orphaned.get()) {
                        fields.put("orphaned", "true");
                        event.put("orphaned", "true");
                    }
                    return recordTerminalWithRetry(
                            ticket.taskId(),
                            "failed",
                            fields,
                            event
                    );
                }))
                .then(Mono.defer(() -> tempFiles.delete(path)
                        .onErrorResume(cleanupError -> Mono.empty())))
                .then(Mono.error(exception));
    }

    private Mono<Void> recordTerminalWithRetry(
            String taskId,
            String status,
            Map<String, String> fields,
            Map<String, String> event
    ) {
        return Mono.defer(() -> sessions.recordTerminal(taskId, status, fields, event))
                .retryWhen(Retry.max(2)
                        .filter(error -> !(error instanceof TransferException))
                        .onRetryExhaustedThrow((spec, signal) -> signal.failure()));
    }

    private static TransferException normalizeFinalizeError(Throwable error) {
        if (error instanceof TransferException exception) {
            return exception;
        }
        return new TransferException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "transfer_finalize_failed",
                "Upload finalization failed"
        );
    }

    private static Map<String, String> completionEvent(
            TransferTicket ticket,
            VerifiedFile file
    ) {
        Map<String, String> event = new HashMap<>();
        event.put("event_id", UUID.randomUUID().toString());
        event.put("task_id", ticket.taskId());
        event.put("object_key", ticket.objectKey());
        event.put("size", Long.toString(file.size()));
        event.put("sha256", file.sha256());
        event.put("status", "completed");
        event.put("completed_at", Long.toString(Instant.now().getEpochSecond()));
        return event;
    }

    private static Map<String, String> failureEvent(
            TransferTicket ticket,
            String error
    ) {
        Map<String, String> event = new HashMap<>();
        event.put("event_id", UUID.randomUUID().toString());
        event.put("task_id", ticket.taskId());
        event.put("object_key", ticket.objectKey());
        event.put("status", "failed");
        event.put("error", error);
        event.put("completed_at", Long.toString(Instant.now().getEpochSecond()));
        return event;
    }

    private void validateRequest(
            TransferTicket ticket,
            UploadContentRange range,
            Long contentLength,
            String chunkSha256
    ) {
        if (range.total() != ticket.maxSize()) {
            throw new TransferException(
                    HttpStatus.BAD_REQUEST,
                    "size_mismatch",
                    "Content-Range total does not match ticket max_size"
            );
        }
        if (range.length() > properties.chunkSize()) {
            throw new TransferException(
                    HttpStatus.PAYLOAD_TOO_LARGE,
                    "chunk_too_large",
                    "A transfer chunk must not exceed " + properties.chunkSize() + " bytes"
            );
        }
        long actualContentLength = contentLength == null ? -1 : contentLength;
        if ((!range.empty() && actualContentLength != range.length())
                || (range.empty() && actualContentLength > 0)) {
            throw new TransferException(
                    HttpStatus.BAD_REQUEST,
                    "content_length_mismatch",
                    "Content-Length must match Content-Range"
            );
        }
        if (StringUtils.hasText(chunkSha256)
                && !chunkSha256.matches("(?i)[0-9a-f]{64}")) {
            throw new TransferException(
                    HttpStatus.BAD_REQUEST,
                    "invalid_chunk_sha256",
                    "X-Chunk-SHA256 must be a hexadecimal SHA-256 digest"
            );
        }
    }

    public static void validateSession(TransferSession session, TransferTicket ticket) {
        boolean matches = session.taskId().equals(ticket.taskId())
                && session.username().equals(ticket.username())
                && session.operation() == ticket.operation()
                && session.objectKey().equals(ticket.objectKey())
                && session.maxSize() == ticket.maxSize()
                && (ticket.expectedSha256() == null || Objects.equals(
                    normalizeSha256(session.expectedSha256()),
                    normalizeSha256(ticket.expectedSha256())
                ));
        if (!matches) {
            throw new TransferException(
                    HttpStatus.FORBIDDEN,
                    "session_ticket_mismatch",
                    "Redis session does not match the signed transfer ticket"
            );
        }
    }

    private static UploadResult result(
            TransferTicket ticket,
            String status,
            long offset,
            String sha256,
            boolean completed,
            boolean retry
    ) {
        return new UploadResult(
                ticket.taskId(),
                status,
                ticket.objectKey(),
                ticket.maxSize(),
                sha256,
                offset,
                completed,
                retry
        );
    }

    private static TransferException offsetConflict(long expectedOffset) {
        return new TransferException(
                HttpStatus.CONFLICT,
                "offset_conflict",
                "Chunk does not start at the current upload offset",
                expectedOffset
        );
    }

    private static String normalizeSha256(String value) {
        return StringUtils.hasText(value) ? value.toLowerCase() : null;
    }
}

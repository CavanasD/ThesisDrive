package com.thesis.transfer.upload;

import com.thesis.transfer.config.TransferProperties;
import com.thesis.transfer.web.TransferException;
import jakarta.annotation.PostConstruct;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.concurrent.atomic.AtomicLong;

@Component
public class TempFileService {
    private final Path directory;

    public TempFileService(TransferProperties properties) {
        this.directory = properties.tempDirectory().toAbsolutePath().normalize();
    }

    @PostConstruct
    void initialize() throws IOException {
        Files.createDirectories(directory);
    }

    public Path pathFor(String taskId) {
        return directory.resolve(sha256(taskId) + ".part");
    }

    public Mono<ChunkWriteResult> write(
            Path path,
            long start,
            long expectedLength,
            String expectedChunkSha256,
            Flux<DataBuffer> body
    ) {
        return Mono.using(
                        () -> open(path, start),
                        channel -> writeBody(
                                channel,
                                body,
                                expectedLength,
                                expectedChunkSha256
                        ),
                        TempFileService::closeQuietly
                )
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<VerifiedFile> verify(
            Path path,
            long expectedSize,
            String expectedSha256
    ) {
        return Mono.fromCallable(() -> {
                    long size = Files.size(path);
                    if (size != expectedSize) {
                        throw new TransferException(
                                HttpStatus.UNPROCESSABLE_ENTITY,
                                "size_mismatch",
                                "Uploaded size does not match the transfer ticket"
                        );
                    }
                    MessageDigest digest = digest();
                    try (var input = Files.newInputStream(path)) {
                        byte[] buffer = new byte[64 * 1024];
                        int read;
                        while ((read = input.read(buffer)) >= 0) {
                            if (read > 0) {
                                digest.update(buffer, 0, read);
                            }
                        }
                    }
                    String actualSha256 = HexFormat.of().formatHex(digest.digest());
                    if (expectedSha256 != null
                            && !MessageDigest.isEqual(
                            actualSha256.getBytes(), expectedSha256.getBytes())) {
                        throw new TransferException(
                                HttpStatus.UNPROCESSABLE_ENTITY,
                                "sha256_mismatch",
                                "Uploaded SHA-256 does not match the transfer ticket"
                        );
                    }
                    return new VerifiedFile(path, size, actualSha256);
                })
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<Void> createEmpty(Path path) {
        return Mono.fromRunnable(() -> {
                    try {
                        Files.newOutputStream(
                                path,
                                StandardOpenOption.CREATE,
                                StandardOpenOption.TRUNCATE_EXISTING
                        ).close();
                    } catch (IOException exception) {
                        throw new IllegalStateException("Unable to create empty upload", exception);
                    }
                })
                .subscribeOn(Schedulers.boundedElastic())
                .then();
    }

    public Mono<Void> delete(Path path) {
        return Mono.fromRunnable(() -> {
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException ignored) {
                        // Scheduled cleanup will retry after the session TTL.
                    }
                })
                .subscribeOn(Schedulers.boundedElastic())
                .then();
    }

    public long cleanupOlderThan(Instant cutoff) throws IOException {
        long deleted = 0;
        try (var files = Files.list(directory)) {
            for (Path path : files.filter(p -> p.getFileName().toString().endsWith(".part")).toList()) {
                if (Files.getLastModifiedTime(path).toInstant().isBefore(cutoff)
                        && Files.deleteIfExists(path)) {
                    deleted++;
                }
            }
        }
        return deleted;
    }

    private static FileChannel open(Path path, long start) throws IOException {
        if (start == 0) {
            return FileChannel.open(
                    path,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.WRITE,
                    StandardOpenOption.TRUNCATE_EXISTING
            );
        }
        FileChannel channel = FileChannel.open(
                path,
                StandardOpenOption.CREATE,
                StandardOpenOption.WRITE
        );
        channel.position(start);
        return channel;
    }

    private static Mono<ChunkWriteResult> writeBody(
            FileChannel channel,
            Flux<DataBuffer> body,
            long expectedLength,
            String expectedChunkSha256
    ) {
        MessageDigest digest = digest();
        AtomicLong written = new AtomicLong();
        return body
                .publishOn(Schedulers.boundedElastic(), 1)
                .concatMap(buffer -> Mono.fromRunnable(() -> {
                    try {
                        int readable = buffer.readableByteCount();
                        long next = written.get() + readable;
                        if (next > expectedLength) {
                            throw new TransferException(
                                    HttpStatus.BAD_REQUEST,
                                    "content_length_mismatch",
                                    "Request body exceeds Content-Range"
                            );
                        }
                        byte[] bytes = new byte[readable];
                        buffer.read(bytes);
                        ByteBuffer source = ByteBuffer.wrap(bytes);
                        while (source.hasRemaining()) {
                            channel.write(source);
                        }
                        digest.update(bytes);
                        written.set(next);
                    } catch (IOException exception) {
                        throw new IllegalStateException("Unable to write upload chunk", exception);
                    } finally {
                        DataBufferUtils.release(buffer);
                    }
                }), 1)
                .then(Mono.fromCallable(() -> {
                    channel.force(true);
                    long actual = written.get();
                    if (actual != expectedLength) {
                        throw new TransferException(
                                HttpStatus.BAD_REQUEST,
                                "content_length_mismatch",
                                "Request body length does not match Content-Range"
                        );
                    }
                    String actualSha256 = HexFormat.of().formatHex(digest.digest());
                    if (expectedChunkSha256 != null
                            && !actualSha256.equalsIgnoreCase(expectedChunkSha256)) {
                        throw new TransferException(
                                HttpStatus.UNPROCESSABLE_ENTITY,
                                "chunk_sha256_mismatch",
                                "X-Chunk-SHA256 does not match the request body"
                        );
                    }
                    return new ChunkWriteResult(actual, actualSha256);
                }))
                .doOnDiscard(DataBuffer.class, DataBufferUtils::release);
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private static String sha256(String value) {
        return HexFormat.of().formatHex(digest().digest(value.getBytes()));
    }

    private static void closeQuietly(FileChannel channel) {
        try {
            channel.close();
        } catch (IOException ignored) {
        }
    }
}

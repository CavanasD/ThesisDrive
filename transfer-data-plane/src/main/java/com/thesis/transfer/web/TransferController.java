package com.thesis.transfer.web;

import com.thesis.transfer.download.DownloadService;
import com.thesis.transfer.protocol.UploadContentRange;
import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.security.TransferTicketService;
import com.thesis.transfer.upload.UploadResult;
import com.thesis.transfer.upload.UploadService;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.CacheControl;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.InvalidMediaTypeException;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/transfers/{taskId}")
public class TransferController {
    private final TransferTicketService tickets;
    private final UploadService uploads;
    private final DownloadService downloads;

    public TransferController(
            TransferTicketService tickets,
            UploadService uploads,
            DownloadService downloads
    ) {
        this.tickets = tickets;
        this.uploads = uploads;
        this.downloads = downloads;
    }

    @RequestMapping(method = RequestMethod.HEAD)
    public Mono<ResponseEntity<Void>> uploadStatus(
            @PathVariable String taskId,
            @AuthenticationPrincipal Jwt jwt
    ) {
        var ticket = tickets.require(jwt, taskId, TransferOperation.UPLOAD);
        return uploads.status(ticket)
                .map(session -> ResponseEntity.ok()
                        .headers(uploadHeaders(
                                session.offset(),
                                session.maxSize(),
                                session.status()
                        ))
                        .build());
    }

    @PutMapping(consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public Mono<ResponseEntity<?>> upload(
            @PathVariable String taskId,
            @AuthenticationPrincipal Jwt jwt,
            @RequestHeader(HttpHeaders.CONTENT_RANGE) String contentRange,
            @RequestHeader(value = HttpHeaders.CONTENT_LENGTH, required = false) Long contentLength,
            @RequestHeader(value = "X-Chunk-SHA256", required = false) String chunkSha256,
            @RequestBody Flux<DataBuffer> body
    ) {
        var ticket = tickets.require(jwt, taskId, TransferOperation.UPLOAD);
        var range = UploadContentRange.parse(contentRange);
        return uploads.upload(ticket, range, contentLength, chunkSha256, body)
                .map(this::uploadResponse);
    }

    @GetMapping(value = "/content", produces = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public Mono<Void> download(
            @PathVariable String taskId,
            @AuthenticationPrincipal Jwt jwt,
            @RequestHeader(value = HttpHeaders.RANGE, required = false) String rangeHeader,
            ServerHttpResponse response
    ) {
        var ticket = tickets.require(jwt, taskId, TransferOperation.DOWNLOAD);
        return downloads.prepare(ticket, rangeHeader)
                .flatMap(plan -> {
                    var range = plan.range();
                    response.setStatusCode(range.partial()
                            ? HttpStatus.PARTIAL_CONTENT
                            : HttpStatus.OK);
                    response.getHeaders().set(HttpHeaders.ACCEPT_RANGES, "bytes");
                    response.getHeaders().setContentType(contentType(plan.contentType()));
                    response.getHeaders().setContentDisposition(
                            ContentDisposition.attachment()
                                    .filename(
                                            safeFilename(plan.filename()),
                                            StandardCharsets.UTF_8
                                    )
                                    .build()
                    );
                    response.getHeaders().setContentLength(range.length());
                    response.getHeaders().setCacheControl(CacheControl.noStore());
                    response.getHeaders().set("Referrer-Policy", "no-referrer");
                    response.getHeaders().set("X-Content-Type-Options", "nosniff");
                    if (range.partial()) {
                        response.getHeaders().set(HttpHeaders.CONTENT_RANGE, range.contentRange());
                    }
                    String etag = plan.sha256() != null
                            ? plan.sha256()
                            : plan.object().etag();
                    if (etag != null && !etag.isBlank()) {
                        response.getHeaders().setETag('"' + etag.replace("\"", "") + '"');
                    }
                    return response.writeWith(plan.content())
                            .then(Mono.defer(() -> downloads.markCompleted(ticket)));
                });
    }

    private ResponseEntity<?> uploadResponse(UploadResult result) {
        HttpHeaders headers = uploadHeaders(
                result.offset(),
                result.size(),
                result.status()
        );
        if (!result.completed()) {
            return ResponseEntity.noContent().headers(headers).build();
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("task_id", result.taskId());
        body.put("object_key", result.objectKey());
        body.put("size", result.size());
        body.put("sha256", result.sha256());
        body.put("status", "completed");
        body.put("idempotent_retry", result.idempotentRetry());
        return ResponseEntity.status(HttpStatus.CREATED).headers(headers).body(body);
    }

    private static HttpHeaders uploadHeaders(long offset, long length, String status) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("Upload-Offset", Long.toString(offset));
        headers.set("Upload-Length", Long.toString(length));
        headers.set("Upload-Status", status);
        headers.setCacheControl(CacheControl.noStore());
        return headers;
    }

    private static MediaType contentType(String value) {
        if (value == null || value.isBlank()) {
            return MediaType.APPLICATION_OCTET_STREAM;
        }
        try {
            return MediaType.parseMediaType(value);
        } catch (InvalidMediaTypeException exception) {
            return MediaType.APPLICATION_OCTET_STREAM;
        }
    }

    private static String safeFilename(String value) {
        if (value == null || value.isBlank()) {
            return "download";
        }
        StringBuilder sanitized = new StringBuilder(value.length());
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            sanitized.append(character < 0x20 || character == 0x7f ? '_' : character);
        }
        String filename = sanitized.toString();
        int separator = Math.max(filename.lastIndexOf('/'), filename.lastIndexOf('\\'));
        if (separator >= 0) {
            filename = filename.substring(separator + 1);
        }
        filename = filename.strip();
        return filename.isEmpty() || ".".equals(filename) || "..".equals(filename)
                ? "download"
                : filename;
    }
}

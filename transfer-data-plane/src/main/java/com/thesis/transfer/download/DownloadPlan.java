package com.thesis.transfer.download;

import com.thesis.transfer.protocol.HttpByteRange;
import com.thesis.transfer.storage.StoredObject;
import org.springframework.core.io.buffer.DataBuffer;
import reactor.core.publisher.Flux;

public record DownloadPlan(
        StoredObject object,
        String sha256,
        String filename,
        String contentType,
        HttpByteRange range,
        Flux<DataBuffer> content
) {}

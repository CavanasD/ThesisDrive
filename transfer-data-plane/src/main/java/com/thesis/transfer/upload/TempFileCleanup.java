package com.thesis.transfer.upload;

import com.thesis.transfer.config.TransferProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;

@Component
public class TempFileCleanup {
    private static final Logger log = LoggerFactory.getLogger(TempFileCleanup.class);

    private final TempFileService tempFiles;
    private final TransferProperties properties;

    public TempFileCleanup(
            TempFileService tempFiles,
            TransferProperties properties
    ) {
        this.tempFiles = tempFiles;
        this.properties = properties;
    }

    @Scheduled(fixedDelayString = "${transfer.cleanup-interval:1h}")
    public void cleanup() {
        try {
            long deleted = tempFiles.cleanupOlderThan(
                    Instant.now().minus(properties.sessionTtl())
            );
            if (deleted > 0) {
                log.info("Deleted {} expired upload temp files", deleted);
            }
        } catch (Exception exception) {
            log.warn("Unable to clean expired upload temp files", exception);
        }
    }
}

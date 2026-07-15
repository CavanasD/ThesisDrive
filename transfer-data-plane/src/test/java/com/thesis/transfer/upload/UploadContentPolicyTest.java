package com.thesis.transfer.upload;

import com.thesis.transfer.security.TransferOperation;
import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.web.TransferException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class UploadContentPolicyTest {
    @TempDir
    Path directory;

    @Test
    void blocksExistingGatewayDangerousExtensionPolicy() {
        TransferException error = assertThrows(
                TransferException.class,
                () -> UploadContentPolicy.validateMetadata(session("payload.PHP", "text/plain"))
        );

        assertEquals("blocked_file_type", error.code());
    }

    @Test
    void blocksExecutableMagicEvenWhenMetadataClaimsPlainText() throws Exception {
        Path file = directory.resolve("notes.txt");
        Files.write(file, new byte[]{0x7f, 0x45, 0x4c, 0x46, 0x01});

        TransferException error = assertThrows(
                TransferException.class,
                () -> UploadContentPolicy.validateMagic(file, Files.size(file))
        );

        assertEquals("blocked_file_type", error.code());
    }

    @Test
    void permitsOrdinaryAndEmptyFiles() throws Exception {
        Path ordinary = directory.resolve("notes.txt");
        Path empty = directory.resolve("empty.txt");
        Files.writeString(ordinary, "thesis evidence");
        Files.createFile(empty);

        assertDoesNotThrow(() -> UploadContentPolicy.validateMetadata(
                session("notes.txt", "text/plain; charset=utf-8")));
        assertDoesNotThrow(() -> UploadContentPolicy.validateMagic(
                ordinary, Files.size(ordinary)));
        assertDoesNotThrow(() -> UploadContentPolicy.validateMagic(empty, 0));
    }

    private static TransferSession session(String filename, String contentType) {
        return new TransferSession(
                "task-1",
                "alice",
                TransferOperation.UPLOAD,
                "objects/1",
                10,
                filename,
                contentType,
                null,
                0,
                "pending"
        );
    }
}

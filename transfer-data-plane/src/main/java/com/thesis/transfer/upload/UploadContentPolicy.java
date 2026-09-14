package com.thesis.transfer.upload;

import com.thesis.transfer.session.TransferSession;
import com.thesis.transfer.web.TransferException;
import org.springframework.http.HttpStatus;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Set;

final class UploadContentPolicy {
    private static final Set<String> DANGEROUS_EXTENSIONS = Set.of(
            ".php", ".php3", ".php5", ".phtml",
            ".jsp", ".jspx",
            ".py", ".sh", ".bash",
            ".exe", ".dll", ".so",
            ".pl", ".rb", ".lua"
    );
    private static final Set<String> DANGEROUS_CONTENT_TYPES = Set.of(
            "application/x-dosexec",
            "application/x-elf",
            "application/x-executable",
            "application/x-msdownload",
            "application/x-sh",
            "application/x-sharedlib",
            "text/x-shellscript"
    );
    private static final byte[] ELF_MAGIC = {0x7f, 0x45, 0x4c, 0x46};
    private static final byte[] PE_MAGIC = {0x4d, 0x5a};

    private UploadContentPolicy() {
    }

    static void validateMetadata(TransferSession session) {
        String filename = normalize(session.filename());
        if (filename != null) {
            for (String extension : DANGEROUS_EXTENSIONS) {
                if (filename.endsWith(extension)) {
                    throw blocked("Dangerous file extension: " + extension);
                }
            }
        }

        String contentType = normalize(session.contentType());
        if (contentType != null) {
            int parameter = contentType.indexOf(';');
            String mediaType = parameter >= 0
                    ? contentType.substring(0, parameter).strip()
                    : contentType;
            if (DANGEROUS_CONTENT_TYPES.contains(mediaType)) {
                throw blocked("Dangerous declared content type: " + mediaType);
            }
        }
    }

    static void validateMagic(Path path, long size) throws IOException {
        if (size == 0) {
            return;
        }
        byte[] prefix = new byte[ELF_MAGIC.length];
        int length;
        try (InputStream input = Files.newInputStream(path)) {
            length = input.read(prefix);
        }
        if (startsWith(prefix, length, ELF_MAGIC)) {
            throw blocked("ELF binary detected by magic bytes");
        }
        if (startsWith(prefix, length, PE_MAGIC)) {
            throw blocked("PE/EXE binary detected by magic bytes");
        }
    }

    private static boolean startsWith(byte[] value, int length, byte[] prefix) {
        if (length < prefix.length) {
            return false;
        }
        for (int index = 0; index < prefix.length; index++) {
            if (value[index] != prefix[index]) {
                return false;
            }
        }
        return true;
    }

    private static String normalize(String value) {
        return StringUtils.hasText(value) ? value.strip().toLowerCase(Locale.ROOT) : null;
    }

    private static TransferException blocked(String message) {
        return new TransferException(
                HttpStatus.UNSUPPORTED_MEDIA_TYPE,
                "blocked_file_type",
                message
        );
    }
}

package com.thesis.transfer.storage;

import java.io.InputStream;
import java.nio.file.Path;

public interface ObjectStorage {
    StoredObject put(String objectKey, Path source, long size, String sha256) throws Exception;

    StoredObject stat(String objectKey) throws Exception;

    InputStream open(String objectKey, long offset, long length) throws Exception;

    void delete(String objectKey) throws Exception;
}

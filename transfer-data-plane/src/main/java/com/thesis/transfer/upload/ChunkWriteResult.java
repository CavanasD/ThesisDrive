package com.thesis.transfer.upload;

public record ChunkWriteResult(long bytesWritten, String sha256) {}

package com.thesis.transfer.storage;

public record StoredObject(long size, String etag, String sha256) {}

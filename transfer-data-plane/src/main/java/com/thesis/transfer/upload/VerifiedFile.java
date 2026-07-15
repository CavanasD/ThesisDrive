package com.thesis.transfer.upload;

import java.nio.file.Path;

public record VerifiedFile(Path path, long size, String sha256) {}

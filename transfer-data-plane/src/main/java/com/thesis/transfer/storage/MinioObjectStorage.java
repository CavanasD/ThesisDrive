package com.thesis.transfer.storage;

import com.thesis.transfer.config.TransferProperties;
import io.minio.BucketExistsArgs;
import io.minio.GetObjectArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import io.minio.StatObjectArgs;
import org.springframework.stereotype.Component;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

@Component
public class MinioObjectStorage implements ObjectStorage {
    private final MinioClient client;
    private final String bucket;
    private final AtomicBoolean bucketReady = new AtomicBoolean();

    public MinioObjectStorage(MinioClient client, TransferProperties properties) {
        this.client = client;
        this.bucket = properties.minio().bucket();
    }

    @Override
    public StoredObject put(
            String objectKey,
            Path source,
            long size,
            String sha256
    ) throws Exception {
        ensureBucket();
        try (InputStream input = Files.newInputStream(source)) {
            client.putObject(PutObjectArgs.builder()
                    .bucket(bucket)
                    .object(objectKey)
                    .stream(input, size, -1)
                    .contentType("application/octet-stream")
                    .userMetadata(Map.of("sha256", sha256))
                    .build());
        }
        return stat(objectKey);
    }

    @Override
    public StoredObject stat(String objectKey) throws Exception {
        ensureBucket();
        var response = client.statObject(StatObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .build());
        return new StoredObject(
                response.size(),
                response.etag(),
                response.userMetadata().get("sha256")
        );
    }

    @Override
    public InputStream open(String objectKey, long offset, long length) throws Exception {
        ensureBucket();
        return client.getObject(GetObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .offset(offset)
                .length(length)
                .build());
    }

    @Override
    public void delete(String objectKey) throws Exception {
        ensureBucket();
        client.removeObject(RemoveObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .build());
    }

    private synchronized void ensureBucket() throws Exception {
        if (bucketReady.get()) {
            return;
        }
        boolean exists = client.bucketExists(BucketExistsArgs.builder()
                .bucket(bucket)
                .build());
        if (!exists) {
            client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }
        bucketReady.set(true);
    }
}

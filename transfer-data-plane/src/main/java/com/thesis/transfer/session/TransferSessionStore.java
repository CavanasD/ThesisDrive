package com.thesis.transfer.session;

import reactor.core.publisher.Mono;

import java.util.Map;

public interface TransferSessionStore {
    Mono<TransferSession> getRequired(String taskId);

    Mono<LockLease> acquire(String taskId);

    Mono<Void> release(LockLease lease);

    Mono<Long> compareAndSetOffset(String taskId, long expectedOffset, long newOffset);

    Mono<Void> markStatus(String taskId, String status, Map<String, String> extraFields);

    Mono<Void> recordTerminal(
            String taskId,
            String status,
            Map<String, String> extraFields,
            Map<String, String> event
    );
}

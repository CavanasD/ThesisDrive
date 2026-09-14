package com.thesis.transfer.session;

import com.thesis.transfer.config.TransferProperties;
import com.thesis.transfer.web.TransferException;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Repository;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Repository
public class RedisTransferSessionStore implements TransferSessionStore {
    private static final RedisScript<Long> RELEASE_LOCK = RedisScript.of("""
            if redis.call('GET', KEYS[1]) == ARGV[1] then
              return redis.call('DEL', KEYS[1])
            end
            return 0
            """, Long.class);

    private static final RedisScript<Long> ADVANCE_OFFSET = RedisScript.of("""
            local current = tonumber(redis.call('HGET', KEYS[1], 'offset') or '-1')
            if current ~= tonumber(ARGV[1]) then
              return current
            end
            redis.call('HSET', KEYS[1],
              'offset', ARGV[2],
              'status', ARGV[3],
              'expires_at', ARGV[4])
            redis.call('EXPIRE', KEYS[1], ARGV[5])
            return tonumber(ARGV[2])
            """, Long.class);

    private static final RedisScript<Long> RECORD_TERMINAL = RedisScript.of("""
            local session_type = redis.call('TYPE', KEYS[1])['ok']
            if session_type == 'none' then
              return -1
            end
            if session_type ~= 'hash' then
              return redis.error_reply('transfer session key is not a hash')
            end

            local current_status = redis.call('HGET', KEYS[1], 'status')
            if current_status == 'completed' or current_status == 'failed' then
              local current_event_id = redis.call('HGET', KEYS[1], 'terminal_event_id')
              if current_status == ARGV[1] and current_event_id == ARGV[5] then
                return 0
              end
              return -2
            end

            local stream_type = redis.call('TYPE', KEYS[2])['ok']
            if stream_type ~= 'none' and stream_type ~= 'stream' then
              return redis.error_reply('completion key is not a stream')
            end

            local extra_count = tonumber(ARGV[6])
            local extra_start = 7
            local event_count_index = extra_start + (extra_count * 2)
            local event_count = tonumber(ARGV[event_count_index])
            local index = event_count_index + 1
            local stream_args = {KEYS[2], 'MAXLEN', '~', ARGV[4], '*'}
            for _ = 1, event_count do
              table.insert(stream_args, ARGV[index])
              table.insert(stream_args, ARGV[index + 1])
              index = index + 2
            end
            redis.call('XADD', unpack(stream_args))

            index = extra_start
            for _ = 1, extra_count do
              redis.call('HSET', KEYS[1], ARGV[index], ARGV[index + 1])
              index = index + 2
            end
            redis.call('HSET', KEYS[1],
              'status', ARGV[1],
              'expires_at', ARGV[2],
              'terminal_event_id', ARGV[5])
            redis.call('EXPIRE', KEYS[1], ARGV[3])
            return 1
            """, Long.class);

    private final ReactiveStringRedisTemplate redis;
    private final TransferProperties properties;

    public RedisTransferSessionStore(
            ReactiveStringRedisTemplate redis,
            TransferProperties properties
    ) {
        this.redis = redis;
        this.properties = properties;
    }

    @Override
    public Mono<TransferSession> getRequired(String taskId) {
        return redis.<String, String>opsForHash()
                .entries(sessionKey(taskId))
                .collectMap(Map.Entry::getKey, Map.Entry::getValue)
                .filter(values -> !values.isEmpty())
                .switchIfEmpty(Mono.error(new TransferException(
                        HttpStatus.GONE,
                        "session_expired",
                        "Transfer session is missing or expired"
                )))
                .map(TransferSession::from);
    }

    @Override
    public Mono<LockLease> acquire(String taskId) {
        String token = UUID.randomUUID().toString();
        return redis.opsForValue()
                .setIfAbsent(lockKey(taskId), token, properties.lockTtl())
                .flatMap(acquired -> Boolean.TRUE.equals(acquired)
                        ? Mono.just(new LockLease(taskId, token))
                        : Mono.error(new TransferException(
                                HttpStatus.CONFLICT,
                                "transfer_busy",
                                "Another request is currently updating this transfer"
                        )));
    }

    @Override
    public Mono<Void> release(LockLease lease) {
        return redis.execute(
                        RELEASE_LOCK,
                        List.of(lockKey(lease.taskId())),
                        lease.token()
                )
                .then();
    }

    @Override
    public Mono<Long> compareAndSetOffset(
            String taskId,
            long expectedOffset,
            long newOffset
    ) {
        long expiresAt = Instant.now().plus(properties.sessionTtl()).getEpochSecond();
        return redis.execute(
                        ADVANCE_OFFSET,
                        List.of(sessionKey(taskId)),
                        Long.toString(expectedOffset),
                        Long.toString(newOffset),
                        newOffset == expectedOffset ? "receiving" : "receiving",
                        Long.toString(expiresAt),
                        Long.toString(properties.sessionTtl().toSeconds())
                )
                .single();
    }

    @Override
    public Mono<Void> markStatus(
            String taskId,
            String status,
            Map<String, String> extraFields
    ) {
        Map<String, String> fields = new HashMap<>(extraFields);
        fields.put("status", status);
        fields.put(
                "expires_at",
                Long.toString(Instant.now().plus(properties.sessionTtl()).getEpochSecond())
        );
        String key = sessionKey(taskId);
        return redis.<String, String>opsForHash()
                .putAll(key, fields)
                .then(redis.expire(key, properties.sessionTtl()))
                .then();
    }

    @Override
    public Mono<Void> recordTerminal(
            String taskId,
            String status,
            Map<String, String> extraFields,
            Map<String, String> event
    ) {
        String eventId = event.get("event_id");
        if (eventId == null || eventId.isBlank()) {
            return Mono.error(new IllegalArgumentException(
                    "A terminal transfer event must contain event_id"
            ));
        }
        List<String> arguments = new ArrayList<>();
        arguments.add(status);
        arguments.add(Long.toString(
                Instant.now().plus(properties.sessionTtl()).getEpochSecond()
        ));
        arguments.add(Long.toString(properties.sessionTtl().toSeconds()));
        arguments.add(Long.toString(properties.completionStreamMaxLength()));
        arguments.add(eventId);
        arguments.add(Integer.toString(extraFields.size()));
        extraFields.forEach((key, value) -> {
            arguments.add(key);
            arguments.add(value);
        });
        arguments.add(Integer.toString(event.size()));
        event.forEach((key, value) -> {
            arguments.add(key);
            arguments.add(value);
        });

        return redis.execute(
                        RECORD_TERMINAL,
                        List.of(sessionKey(taskId), properties.completionStream()),
                        arguments.toArray()
                )
                .single()
                .flatMap(result -> {
                    if (result == -1) {
                        return Mono.error(new TransferException(
                                HttpStatus.GONE,
                                "session_expired",
                                "Transfer session is missing or expired"
                        ));
                    }
                    if (result == -2) {
                        return Mono.error(new TransferException(
                                HttpStatus.CONFLICT,
                                "terminal_state_conflict",
                                "Transfer already has a different terminal result"
                        ));
                    }
                    return Mono.empty();
                });
    }

    private static String sessionKey(String taskId) {
        return "transfer:session:" + taskId;
    }

    private static String lockKey(String taskId) {
        return "transfer:lock:" + taskId;
    }
}

package com.thesis.transfer.session;

import com.thesis.transfer.config.TransferProperties;
import com.thesis.transfer.web.TransferException;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import reactor.core.publisher.Flux;

import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RedisTransferSessionStoreTest {
    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void terminalScriptUsesCorrectKeysArgumentsAndPublishesBeforeTerminalHash() {
        ReactiveStringRedisTemplate redis = mock(ReactiveStringRedisTemplate.class);
        when(redis.execute(any(RedisScript.class), anyList(), any(Object[].class)))
                .thenReturn(Flux.just(1L));
        RedisTransferSessionStore store = new RedisTransferSessionStore(redis, properties());
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("offset", "12");
        Map<String, String> event = new LinkedHashMap<>();
        event.put("event_id", "event-1");
        event.put("task_id", "task-1");
        event.put("status", "completed");

        store.recordTerminal("task-1", "completed", fields, event).block();

        ArgumentCaptor<RedisScript> script = ArgumentCaptor.forClass(RedisScript.class);
        ArgumentCaptor<List> keys = ArgumentCaptor.forClass(List.class);
        ArgumentCaptor<Object[]> arguments = ArgumentCaptor.forClass(Object[].class);
        verify(redis).execute(script.capture(), keys.capture(), arguments.capture());

        assertEquals(
                List.of("transfer:session:task-1", "transfer:completed"),
                keys.getValue()
        );
        Object[] argv = arguments.getValue();
        assertEquals("completed", argv[0]);
        assertTrue(Long.parseLong((String) argv[1]) > 0);
        assertEquals("86400", argv[2]);
        assertEquals("1000", argv[3]);
        assertEquals("event-1", argv[4]);
        assertEquals("1", argv[5]);
        assertEquals("offset", argv[6]);
        assertEquals("12", argv[7]);
        assertEquals("3", argv[8]);
        assertEquals("event_id", argv[9]);
        assertEquals("event-1", argv[10]);

        String lua = script.getValue().getScriptAsString();
        assertTrue(lua.contains("current_status == 'completed'"));
        assertTrue(lua.contains("current_event_id == ARGV[5]"));
        assertTrue(lua.contains("return -2"));
        assertTrue(lua.contains(
                "local stream_args = {KEYS[2], 'MAXLEN', '~', ARGV[4], '*'}"
        ));
        assertTrue(lua.contains("redis.call('XADD', unpack(stream_args))"));
        assertTrue(lua.indexOf("redis.call('XADD'")
                < lua.indexOf("'terminal_event_id', ARGV[5]"));
    }

    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void differentExistingTerminalStateIsRejected() {
        ReactiveStringRedisTemplate redis = mock(ReactiveStringRedisTemplate.class);
        when(redis.execute(any(RedisScript.class), anyList(), any(Object[].class)))
                .thenReturn(Flux.just(-2L));
        RedisTransferSessionStore store = new RedisTransferSessionStore(redis, properties());

        TransferException exception = assertThrows(
                TransferException.class,
                () -> store.recordTerminal(
                        "task-1",
                        "failed",
                        Map.of("error", "object_store_failure"),
                        Map.of("event_id", "event-2", "status", "failed")
                ).block()
        );

        assertEquals("terminal_state_conflict", exception.code());
    }

    private static TransferProperties properties() {
        return new TransferProperties(
                8L * 1024 * 1024,
                Duration.ofHours(24),
                Duration.ofHours(2),
                Path.of("build/test-uploads"),
                Duration.ofHours(1),
                "transfer:completed",
                1000,
                new TransferProperties.Minio(
                        "http://localhost:9000", "test", "key", "secret"
                ),
                new TransferProperties.Security(
                        "classpath:test.pem", "issuer", "audience", Duration.ofSeconds(30)
                ),
                new TransferProperties.Cors(List.of("http://localhost"))
        );
    }
}

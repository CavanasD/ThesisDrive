"""Observer-only bootstrap, excluded from formal throughput measurements."""
from collections import Counter
import json
import os
from pathlib import Path
import signal
import struct
import sys
import threading
import time

sys.path.insert(0, str(Path.cwd()))
import main
from include.transport import router
from websockets.sync.server import ServerConnection

lock = threading.Lock()
local = threading.local()
active = {}
tails = []
rejections = []
counts = Counter()
original_handle = router.handle_request
original_send = ServerConnection.send
controller = router.admission_controller
original_acquire = controller.acquire_request
original_release = controller.release_request
original_audit = router.log_audit


def handle(stream):
    key = (id(stream.connection._ws), stream.frame_id)
    local.key = key
    with lock:
        active[key] = None
    return original_handle(stream)


def send(self, data, *args, **kwargs):
    result = original_send(self, data, *args, **kwargs)
    if isinstance(data, (bytes, bytearray, memoryview)) and len(data) >= 5:
        frame_id, kind = struct.unpack_from('!IB', data)
        if kind == 1:
            with lock:
                key = (id(self), frame_id)
                if key in active:
                    active[key] = time.perf_counter()
    return result


def release(connection):
    with lock:
        written = active.pop(getattr(local, 'key', None), None)
        if written is not None:
            tails.append((time.perf_counter() - written) * 1000)
    return original_release(connection)


def acquire(connection):
    decision = original_acquire(connection)
    with lock:
        counts['accepted' if decision.allowed else decision.scope] += 1
        if not decision.allowed and len(rejections) < 100:
            rejections.append({'scope': decision.scope,
                'connections': controller._connections,
                'admitted_requests_at_sample': controller._requests,
                'response_written_not_released': sum(t is not None for t in active.values())})
    return decision


def audit(*args, **kwargs):
    with lock:
        counts['audit_calls'] += 1
    return original_audit(*args, **kwargs)


def finish(signum, frame):
    with lock:
        result = {'note': 'Instrumented diagnostic only; timing includes observer overhead. Socket-write completion precedes request-slot release.',
                  'counts': dict(counts), 'rejections': rejections,
                  'write_to_release_ms': list(tails)}
    Path(os.environ['BARE_TRACE_OUT']).write_text(json.dumps(result))
    raise SystemExit(0)


router.handle_request = handle
router.log_audit = audit
ServerConnection.send = send
controller.acquire_request = acquire
controller.release_request = release
signal.signal(signal.SIGTERM, finish)
main.main()

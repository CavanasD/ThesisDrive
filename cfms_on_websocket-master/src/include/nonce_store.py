"""
Nonce store for replay attack protection.

Tracks used nonces with automatic expiration to prevent replay attacks.
Each nonce is stored with the server receive time and automatically expired
after the configured time window.
"""

__all__ = ["NonceStore", "nonce_store"]

import math
import threading
import time
from collections import deque
from typing import Optional

from include.constants import REPLAY_PROTECTION_TIME_WINDOW_SECONDS


class NonceStore:
    """
    Thread-safe store for tracking used nonces to prevent replay attacks.

    Nonces are stored with the server receive time and automatically expired
    when they fall outside the configured time window. Uses an ordered deque
    for efficient O(1) amortized cleanup.
    """

    def __init__(self, time_window: float = REPLAY_PROTECTION_TIME_WINDOW_SECONDS):
        self._nonces: dict[str, float] = {}  # nonce -> server receive time
        self._expiry_queue: deque[tuple[float, str]] = deque()  # (expires_at, nonce)
        self._lock = threading.Lock()
        self._time_window = time_window

    def _cleanup_expired(self) -> None:
        """Remove nonces that have expired, using the ordered expiry queue."""
        now = time.time()
        while self._expiry_queue and self._expiry_queue[0][0] <= now:
            expires_at, nonce = self._expiry_queue.popleft()
            self._nonces.pop(nonce, None)

    def validate_and_store(self, nonce: str, timestamp: float) -> Optional[str]:
        """
        Validate a nonce and timestamp, storing it if valid.

        Args:
            nonce: The unique nonce string from the client request.
            timestamp: The timestamp from the client request.

        Returns:
            None if valid, or an error message string if invalid.
        """
        # Reject non-finite timestamps (NaN, Infinity)
        if not math.isfinite(timestamp):
            return "Request timestamp is not a finite number"

        now = time.time()

        # Check timestamp is within acceptable window
        if abs(now - timestamp) > self._time_window:
            return "Request timestamp is outside the acceptable time window"

        with self._lock:
            self._cleanup_expired()

            # Check if nonce has already been used
            if nonce in self._nonces:
                return "Duplicate nonce detected: possible replay attack"

            # Store the nonce with server receive time for consistent expiry
            self._nonces[nonce] = now
            self._expiry_queue.append((now + self._time_window, nonce))

        return None


# Global singleton instance
nonce_store = NonceStore()
